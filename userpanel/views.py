# Standard imports for view helpers and profile parsing.
from datetime import datetime, timedelta

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Q
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .utils import build_chat_transcript, summarize_chat_with_gemini, to_aware_datetime
from .services.ai_service import detect_emotion


from .models import User, Message, BlockedUser, ReportedUser


def attach_profile_url(user):
    user.profile_picture_url = user.profile_picture.url if getattr(user, 'profile_picture', None) else ''
    return user


def get_chat_relation_state(current_user, other_user):
    block_by_current = BlockedUser.objects.filter(blocker=current_user, blocked=other_user).exists()
    block_by_other = BlockedUser.objects.filter(blocker=other_user, blocked=current_user).exists()
    report_by_current = ReportedUser.objects.filter(reporter=current_user, reported=other_user).exists()
    report_by_other = ReportedUser.objects.filter(reporter=other_user, reported=current_user).exists()
    return {
        'blocked_by_current': block_by_current,
        'blocked_by_other': block_by_other,
        'is_blocked_chat': block_by_current or block_by_other,
        'reported_by_current': report_by_current,
        'reported_by_other': report_by_other,
    }


def broadcast_profile_update(user):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    async_to_sync(channel_layer.group_send)(
        'global_users',
        {
            'type': 'profile_update_event',
            'user_id': user.id,
            'name': user.name,
            'email': user.email,
            'profile_picture_url': user.profile_picture.url if user.profile_picture else '',
        }
    )


def broadcast_moderation_update(actor_id, target_id, action):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    users = sorted([str(actor_id), str(target_id)])
    room_group_name = f'chat_{users[0]}_{users[1]}'

    async_to_sync(channel_layer.group_send)(
        room_group_name,
        {
            'type': 'moderation_event',
            'action': action,
            'actor_id': int(actor_id),
            'target_id': int(target_id),
        }
    )

# 🔹 Chat View
def chat_view(request, user_id):
    if 'user_id' not in request.session:
        return redirect('login')

    current_user = attach_profile_url(User.objects.get(id=request.session['user_id']))

    other_user = attach_profile_url(User.objects.get(id=user_id))
    relation_state = get_chat_relation_state(current_user, other_user)

    # 🔥 ✅ MARK AS READ (IMPORTANT)
    Message.objects.filter(
        sender=other_user,
        receiver=current_user,
        is_read=False
    ).update(is_read=True)

    # 🔥 Only users jinke saath chat hui hai
    users = User.objects.filter(
        Q(sent_messages__receiver=current_user) | 
        Q(received_messages__sender=current_user)
    ).distinct().exclude(id=current_user.id)

    # 🔥 Messages between current & selected user
    messages = Message.objects.filter(
        sender__in=[current_user, other_user],
        receiver__in=[current_user, other_user]
    ).order_by('timestamp')
    last_message = messages.last()
    last_message_date = last_message.timestamp.strftime('%Y-%m-%d') if last_message else ''

    # 🔥 Enhance user list
    user_list = []
    for u in users:
        attach_profile_url(u)
        last_msg = Message.objects.filter(
            sender__in=[current_user, u],
            receiver__in=[current_user, u]
        ).order_by('-timestamp').first()
        unread = Message.objects.filter(
            sender=u,
            receiver=current_user,
            is_read=False
        ).count()
        u.last_message = last_msg.message if last_msg else ""
        u.unread_count = unread
        user_list.append(u)

    return render(request, 'userpanel/dashboard.html', {
        'user': current_user,
        'users': user_list,
        'messages': messages,
        'other_user': other_user,
        'last_message_date': last_message_date,
        **relation_state,
    })


# 🔹 Register View
def register(request):
    if request.method == "POST":
        name = request.POST.get('name')
        email = request.POST.get('email')
        password = make_password(request.POST.get('password'))

        # Check if email already exists
        if User.objects.filter(email=email).exists():
            return render(request, 'userpanel/register.html', {
                'error': 'Email already exists'
            })

        # Create user
        User.objects.create(
            name=name,
            email=email,
            password=password
        )

        return redirect('login')

    return render(request, 'userpanel/register.html')


# 🔹 Login View
def login_view(request):
    if request.method == "POST":
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        if not email or not password:
            return render(request, 'userpanel/login.html', {
                'error': 'Email and password are required.'
            })

        try:
            user = User.objects.get(email__iexact=email)

            # Support legacy plain-text passwords and upgrade them on successful login.
            is_valid_password = check_password(password, user.password) or (user.password == password)

            if is_valid_password:
                if user.password == password:
                    user.password = make_password(password)
                    user.save(update_fields=['password'])

                request.session['user_id'] = user.id
                return redirect('welcome')
            else:
                return render(request, 'userpanel/login.html', {
                    'error': 'Invalid password'
                })

        except User.DoesNotExist:
            return render(request, 'userpanel/login.html', {
                'error': 'User not found'
            })

    return render(request, 'userpanel/login.html')


# 🔹 Dashboard View


def dashboard(request):
    if 'user_id' not in request.session:
        return redirect('login')

    current_user = attach_profile_url(User.objects.get(id=request.session['user_id']))

    # If a user is selected (?user=ID), load chat and mark their incoming messages as read.
    other_user = None
    messages = []
    relation_state = {
        'blocked_by_current': False,
        'blocked_by_other': False,
        'is_blocked_chat': False,
        'reported_by_current': False,
        'reported_by_other': False,
    }
    other_user_id = request.GET.get('user')
    if other_user_id:
        try:
            other_user = attach_profile_url(User.objects.get(id=other_user_id))
            relation_state = get_chat_relation_state(current_user, other_user)

            Message.objects.filter(
                sender=other_user,
                receiver=current_user,
                is_read=False
            ).update(is_read=True)

            messages = Message.objects.filter(
                sender__in=[current_user, other_user],
                receiver__in=[current_user, other_user]
            ).order_by('timestamp')
        except User.DoesNotExist:
            other_user = None
            messages = []

    # सिर्फ chat वाले users (sidebar में default)
    chat_users = User.objects.filter(
        Q(sent_messages__receiver=current_user) | 
        Q(received_messages__sender=current_user)
    ).distinct().exclude(id=current_user.id)

    # सभी users (search के लिए)
    all_users = User.objects.exclude(id=current_user.id)

    user_list = []
    for u in all_users:
        attach_profile_url(u)
        last_msg = Message.objects.filter(
            sender__in=[current_user, u],
            receiver__in=[current_user, u]
        ).order_by('-timestamp').first()
        unread = Message.objects.filter(
            sender=u,
            receiver=current_user,
            is_read=False
        ).count()
        u.last_message = last_msg.message if last_msg else ""
        u.unread_count = unread
        u.has_chat = u in chat_users
        user_list.append(u)

    last_message = messages.last() if hasattr(messages, 'last') else None
    last_message_date = last_message.timestamp.strftime('%Y-%m-%d') if last_message else ''

    return render(request, 'userpanel/dashboard.html', {
        'user': current_user,
        'users': user_list,
        'messages': messages,
        'other_user': other_user,
        'last_message_date': last_message_date,
        **relation_state,
    })


def profile_view(request):
    if 'user_id' not in request.session:
        return redirect('login')

    current_user = attach_profile_url(User.objects.get(id=request.session['user_id']))
    error = None

    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        date_of_birth_raw = request.POST.get('date_of_birth', '').strip()
        gender = request.POST.get('gender', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        location = request.POST.get('location', '').strip()
        bio = request.POST.get('bio', '').strip()
        profile_picture = request.FILES.get('profile_picture')

        if not name:
            error = 'Name is required.'
        elif not email:
            error = 'Email is required.'
        elif User.objects.filter(email=email).exclude(id=current_user.id).exists():
            error = 'Email already exists.'
        else:
            current_user.name = name
            current_user.email = email
            current_user.gender = gender
            current_user.phone_number = phone_number
            current_user.location = location
            current_user.bio = bio

            try:
                if date_of_birth_raw:
                    current_user.date_of_birth = datetime.strptime(date_of_birth_raw, '%Y-%m-%d').date()
                else:
                    current_user.date_of_birth = None

                if profile_picture:
                    current_user.profile_picture = profile_picture

                current_user.save()
                broadcast_profile_update(current_user)
                return redirect(f"{reverse('profile')}?saved=1")
            except ValueError:
                error = 'Please enter a valid date of birth.'

    return render(request, 'userpanel/profile_edit.html', {
        'user': current_user,
        'error': error,
        'saved': request.GET.get('saved') == '1',
        'gender_choices': [
            ('', 'Select gender'),
            ('male', 'Male'),
            ('female', 'Female'),
            ('other', 'Other'),
            ('prefer_not_to_say', 'Prefer not to say'),
        ],
    })


def view_profile(request, user_id):
    if 'user_id' not in request.session:
        return redirect('login')

    current_user = User.objects.get(id=request.session['user_id'])
    try:
        profile_user = attach_profile_url(User.objects.get(id=user_id))
    except User.DoesNotExist:
        return redirect('dashboard')

    return render(request, 'userpanel/view_profile.html', {
        'user': current_user,
        'profile_user': profile_user,
    })


def logout_view(request):
    request.session.flush()
    return redirect('login')
# Send message (AJAX)
def send_message(request):
    if request.method != "POST":
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    sender = User.objects.get(id=request.session['user_id'])
    receiver_id = request.POST.get('receiver_id')
    text = request.POST.get('message', '')
    file = request.FILES.get('file')

    if not receiver_id:
        return JsonResponse({'error': 'Receiver is required'}, status=400)

    receiver = User.objects.get(id=receiver_id)

    # Reports are informational for now; moderation happens later.
    if ReportedUser.objects.filter(reporter=receiver, reported=sender).exists():
        pass

    # If receiver blocked sender, allow local send feel but do not deliver/store.
    if BlockedUser.objects.filter(blocker=receiver, blocked=sender).exists():
        now_local = timezone.localtime(timezone.now())
        if file:
            return JsonResponse({'error': 'Blocked user: file cannot be delivered.'}, status=403)
        return JsonResponse({
            'message_id': None,
            'message': text,
            'sender': sender.name,
            'file_url': None,
            'file_name': None,
            'timestamp': now_local.isoformat(),
            'time_label': now_local.strftime('%I:%M %p').lstrip('0'),
            'date_key': now_local.strftime('%Y-%m-%d'),
            'date_label': now_local.strftime('%a, %d %b %Y'),
            'local_only': True,
            'status': 'ok',
        })

    msg = Message.objects.create(
        sender=sender,
        receiver=receiver,
        message=text,
        file=file if file else None
    )
    msg_local = timezone.localtime(msg.timestamp)

    file_url = msg.file.url if msg.file else None
    file_name = msg.file.name if msg.file else None

    return JsonResponse({
        'message_id': msg.id,
        'message': msg.message,
        'sender': sender.name,
        'file_url': file_url,
        'file_name': file_name,
        'timestamp': msg_local.isoformat(),
        'time_label': msg_local.strftime('%I:%M %p').lstrip('0'),
        'date_key': msg_local.strftime('%Y-%m-%d'),
        'date_label': msg_local.strftime('%a, %d %b %Y'),
        'local_only': False,
    })


@require_POST
def block_user(request):
    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    blocker = User.objects.get(id=request.session['user_id'])
    target_id = request.POST.get('user_id')

    if not target_id:
        return JsonResponse({'error': 'Target user required'}, status=400)

    if str(blocker.id) == str(target_id):
        return JsonResponse({'error': 'You cannot block yourself'}, status=400)

    try:
        blocked = User.objects.get(id=target_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    BlockedUser.objects.get_or_create(blocker=blocker, blocked=blocked)
    broadcast_moderation_update(blocker.id, blocked.id, 'block')

    return JsonResponse({'status': 'ok', 'message': 'User blocked'})


@require_POST
def unblock_user(request):
    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    blocker = User.objects.get(id=request.session['user_id'])
    target_id = request.POST.get('user_id')

    if not target_id:
        return JsonResponse({'error': 'Target user required'}, status=400)

    BlockedUser.objects.filter(blocker=blocker, blocked_id=target_id).delete()
    broadcast_moderation_update(blocker.id, target_id, 'unblock')
    return JsonResponse({'status': 'ok', 'message': 'User unblocked'})


@require_POST
def report_user(request):
    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    reporter = User.objects.get(id=request.session['user_id'])
    target_id = request.POST.get('user_id')

    if not target_id:
        return JsonResponse({'error': 'Target user required'}, status=400)
    if str(reporter.id) == str(target_id):
        return JsonResponse({'error': 'You cannot report yourself'}, status=400)

    try:
        reported = User.objects.get(id=target_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    ReportedUser.objects.get_or_create(reporter=reporter, reported=reported)
    broadcast_moderation_update(reporter.id, reported.id, 'report')
    return JsonResponse({'status': 'ok', 'message': 'User reported'})


@require_POST
def delete_chat(request):
    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    current_user = User.objects.get(id=request.session['user_id'])
    other_user_id = request.POST.get('user_id')

    if not other_user_id:
        return JsonResponse({'error': 'Target user required'}, status=400)

    try:
        other_user = User.objects.get(id=other_user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    deleted_count, _ = Message.objects.filter(
        sender__in=[current_user, other_user],
        receiver__in=[current_user, other_user]
    ).delete()

    return JsonResponse({'status': 'ok', 'deleted_messages': deleted_count})


@require_POST
def edit_message(request):
    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    message_id = request.POST.get('message_id')
    new_message = request.POST.get('message', '').strip()

    if not message_id:
        return JsonResponse({'error': 'Message id required'}, status=400)
    if not new_message:
        return JsonResponse({'error': 'Message cannot be empty'}, status=400)

    try:
        message = Message.objects.get(id=message_id, sender_id=request.session['user_id'])
    except Message.DoesNotExist:
        return JsonResponse({'error': 'Message not found'}, status=404)

    if BlockedUser.objects.filter(
        Q(blocker_id=request.session['user_id'], blocked=message.receiver) |
        Q(blocker=message.receiver, blocked_id=request.session['user_id'])
    ).exists():
        return JsonResponse({'error': 'Editing disabled for blocked chat'}, status=403)

    message.message = new_message
    message.edited_at = timezone.now()
    message.save(update_fields=['message', 'edited_at'])

    return JsonResponse({
        'status': 'ok',
        'message_id': message.id,
        'message': message.message,
        'edited_at': message.edited_at.isoformat(),
    })


@require_POST
def delete_message(request):
    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    message_id = request.POST.get('message_id')
    if not message_id:
        return JsonResponse({'error': 'Message id required'}, status=400)

    try:
        message = Message.objects.get(id=message_id, sender_id=request.session['user_id'])
    except Message.DoesNotExist:
        return JsonResponse({'error': 'Message not found'}, status=404)

    message.delete()
    return JsonResponse({'status': 'ok', 'message_id': message_id})



def summarize_chat(request):
    if request.method != "POST":
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        current_user = User.objects.get(id=request.session['user_id'])
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    other_user_id = request.POST.get('user_id')
    start_raw = request.POST.get('start_datetime')
    end_raw = request.POST.get('end_datetime')
    language = (request.POST.get('language') or 'English').strip()

    if not other_user_id:
        return JsonResponse({'error': 'Chat user is required'}, status=400)

    try:
        other_user = User.objects.get(id=other_user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Selected user not found'}, status=404)

    start_dt = to_aware_datetime(start_raw)
    end_dt = to_aware_datetime(end_raw)

    if not start_dt or not end_dt:
        return JsonResponse({'error': 'Please provide valid start and end datetime'}, status=400)

    if start_dt >= end_dt:
        return JsonResponse({'error': 'Start datetime must be before end datetime'}, status=400)

    # datetime-local uses minute precision; include the complete selected end minute.
    end_dt_exclusive = end_dt + timedelta(minutes=1)

    # Query only selected window and cap records to reduce token usage.
    chat_messages = Message.objects.filter(
        sender__in=[current_user, other_user],
        receiver__in=[current_user, other_user],
        timestamp__gte=start_dt,
        timestamp__lt=end_dt_exclusive,
    ).select_related('sender').order_by('timestamp')[:80]

    transcript = build_chat_transcript(chat_messages, max_messages=80, max_chars=9000)

    if not transcript:
        return JsonResponse({'summary': 'No messages found in this time range.'})

    summary = summarize_chat_with_gemini(transcript, language=language)

    return JsonResponse({'summary': summary})


@require_POST
def detect_message_emotion(request):
    if 'user_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    current_user_id = request.session['user_id']
    chat_user_id = request.POST.get('user_id')
    message_text = (request.POST.get('message') or '').strip()

    if not chat_user_id:
        return JsonResponse({'error': 'Chat user is required'}, status=400)

    try:
        current_user = User.objects.get(id=current_user_id)
        other_user = User.objects.get(id=chat_user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    # Ensure request is made for an actual chat participant context.
    has_any_chat = Message.objects.filter(
        sender__in=[current_user, other_user],
        receiver__in=[current_user, other_user],
    ).exists()

    if not has_any_chat and str(current_user.id) == str(other_user.id):
        return JsonResponse({'error': 'Invalid chat user'}, status=400)

    emotion_label, emotion_emoji, source = detect_emotion(message_text)

    return JsonResponse({
        'emotion': emotion_label,
        'emoji': emotion_emoji,
        'source': source,
    })
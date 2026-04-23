import json
from channels.generic.websocket import AsyncWebsocketConsumer
from urllib.parse import parse_qs
from asgiref.sync import sync_to_async
from django.utils import timezone
from .models import Message, User, BlockedUser, ReportedUser


class ChatConsumer(AsyncWebsocketConsumer):

    # =========================
    # 🔥 CONNECT
    # =========================
    async def connect(self):

        self.other_user_id = self.scope['url_route']['kwargs']['user_id']

        query = parse_qs(self.scope["query_string"].decode())
        self.current_user_id = query.get("user_id", [None])[0]

        if not self.current_user_id or self.current_user_id == "None":
            await self.close()
            return

        users = sorted([self.current_user_id, self.other_user_id])
        self.room_group_name = f'chat_{users[0]}_{users[1]}'

        # 🔥 join groups
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.channel_layer.group_add("global_users", self.channel_name)

        # 🔥 set online
        await self.set_user_online(True)

        # 🔥 broadcast all online users
        await self.broadcast_online_users()

        print("✅ CONNECTED:", self.room_group_name)

        await self.accept()


    # =========================
    # 🔥 DISCONNECT
    # =========================
    async def disconnect(self, close_code):
        try:
            if self.current_user_id:
                await self.set_user_online(False)
                await self.broadcast_online_users()
        except Exception as e:
            print(f"[DISCONNECT ERROR] {e}")
        finally:
            if hasattr(self, "room_group_name"):
                await self.channel_layer.group_discard(
                    self.room_group_name,
                    self.channel_name
                )
            await self.channel_layer.group_discard(
                "global_users",
                self.channel_name
            )

    # =========================
    # 🔥 RECEIVE
    # =========================
    async def receive(self, text_data):
        data = json.loads(text_data)

        # 🔹 typing
        if data.get('type') == 'typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'typing_event',
                    'sender': self.current_user_id
                }
            )
            return

        if data.get('type') == 'stop_typing':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'stop_typing_event',
                    'sender': self.current_user_id
                }
            )
            return

        # 🔹 READ EVENT (IMPORTANT FIX)
        if data.get('type') == 'read_messages':

            await self.mark_messages_read()

            # 🔥 broadcast to sender (double tick)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'read_event',
                    'reader': self.current_user_id
                }
            )
            return

        # 🔥 NORMAL MESSAGE
        message = data.get('message')

        if not message:
            return

        if await self.is_sender_reported_by_receiver():
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'You cannot send messages in this chat.'
            }))
            return

        if await self.is_receiver_blocking_sender():
            sender = await self.get_current_user()
            await self.send(text_data=json.dumps({
                'type': 'message',
                'message': message,
                'sender_id': self.current_user_id,
                'sender_name': sender.name,
                'timestamp': timezone.now().isoformat(),
                'msg_id': None,
                'local_only': True,
            }))
            return

        msg = await self.save_message(message)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': msg.message,
                'sender_id': msg.sender_id,
                'sender_name': msg.sender.name,
                'timestamp': msg.timestamp.isoformat(),
                'msg_id': msg.id
            }
        )

    # =========================
    # 🔥 SEND MESSAGE
    # =========================
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'sender_id': event['sender_id'],
            'sender_name': event.get('sender_name', ''),
            'timestamp': event.get('timestamp'),
            'msg_id': event['msg_id']
        }))

    # =========================
    # 🔥 TYPING
    # =========================
    async def typing_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'sender': event['sender']
        }))

    async def stop_typing_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'stop_typing',
            'sender': event['sender']
        }))

    # =========================
    # 🔥 ONLINE/OFFLINE
    # =========================
    async def user_status(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status',
            'online_users': event['online_users']
        }))

    async def profile_update_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'profile_update',
            'user_id': event['user_id'],
            'name': event['name'],
            'email': event['email'],
            'profile_picture_url': event.get('profile_picture_url', ''),
        }))

    async def moderation_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'moderation',
            'action': event.get('action'),
            'actor_id': event.get('actor_id'),
            'target_id': event.get('target_id'),
        }))

    @sync_to_async
    def get_all_online_users(self):
        # Return a list of user IDs who are online
        from .models import User
        return list(User.objects.filter(is_online=True).values_list('id', flat=True))

    async def broadcast_online_users(self):
        online_users = await self.get_all_online_users()
        await self.channel_layer.group_send(
            "global_users",
            {
                "type": "user_status",
                "online_users": online_users
            }
        )

    # =========================
    # 🔥 READ EVENT (FIXED)
    # =========================
    async def read_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read',
            'reader': event['reader']
        }))

    # =========================
    # 🔥 DB
    # =========================
    @sync_to_async
    def save_message(self, message):
        sender = User.objects.get(id=self.current_user_id)
        receiver = User.objects.get(id=self.other_user_id)

        return Message.objects.create(
            sender=sender,
            receiver=receiver,
            message=message,
            is_read=False
        )

    @sync_to_async
    def get_current_user(self):
        return User.objects.get(id=self.current_user_id)

    @sync_to_async
    def mark_messages_read(self):
        Message.objects.filter(
            sender=self.other_user_id,
            receiver=self.current_user_id,
            is_read=False
        ).update(is_read=True)

    @sync_to_async
    def is_receiver_blocking_sender(self):
        return BlockedUser.objects.filter(
            blocker_id=self.other_user_id,
            blocked_id=self.current_user_id,
        ).exists()

    @sync_to_async
    def is_sender_reported_by_receiver(self):
        return ReportedUser.objects.filter(
            reporter_id=self.other_user_id,
            reported_id=self.current_user_id,
        ).exists()

    @sync_to_async
    def set_user_online(self, status):
        try:
            user = User.objects.get(id=self.current_user_id)
            user.is_online = status
            user.save()
            print(f"[USER ONLINE STATUS] User {user.id} set to {status}")
        except Exception as e:
            print(f"[set_user_online ERROR] {e}")
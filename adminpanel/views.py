from django.shortcuts import render, redirect
from .models import AdminUser
from userpanel.models import User
from django.contrib.auth.hashers import check_password


def admin_login(request):
    if request.method == "POST":
        admin_id = request.POST.get('admin_id')
        password = request.POST.get('password')

        try:
            admin = AdminUser.objects.get(admin_id=admin_id)

            if check_password(password, admin.password):
                request.session['admin_id'] = admin.id
                return redirect('admin_dashboard')
            else:
                return render(request, 'adminpanel/admin_login.html', {
                    'error': 'Invalid password'
                })

        except AdminUser.DoesNotExist:
            return render(request, 'adminpanel/admin_login.html', {
                'error': 'Admin not found'
            })

    return render(request, 'adminpanel/admin_login.html')


def admin_dashboard(request):
    if 'admin_id' not in request.session:
        return redirect('admin_login')

    users = User.objects.all()

    return render(request, 'adminpanel/admin_dashboard.html', {
        'users': users
    })


def admin_logout(request):
    request.session.flush()
    return redirect('admin_login')
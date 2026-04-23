from django.urls import path
from . import views

from django.views.generic import TemplateView

urlpatterns = [
    path('', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    path('view-profile/<int:user_id>/', views.view_profile, name='view_profile'),
    path('welcome/', TemplateView.as_view(template_name='userpanel/welcome.html'), name='welcome'),
    path('logout/', views.logout_view, name='logout'),
    path('chat/<int:user_id>/', views.chat_view, name='chat'),
    path('send-message/', views.send_message, name='send_message'),
    path('block-user/', views.block_user, name='block_user'),
    path('unblock-user/', views.unblock_user, name='unblock_user'),
    path('report-user/', views.report_user, name='report_user'),
    path('delete-chat/', views.delete_chat, name='delete_chat'),
    path('edit-message/', views.edit_message, name='edit_message'),
    path('delete-message/', views.delete_message, name='delete_message'),
    path('summarize-chat/', views.summarize_chat, name='summarize_chat'),
]
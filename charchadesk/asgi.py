import os
import django

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'charchadesk.settings')

# 🔥 VERY IMPORTANT
django.setup()

import userpanel.routing  # ✅ ab yaha import karo

application = ProtocolTypeRouter({
    "http": get_asgi_application(),

    "websocket": AuthMiddlewareStack(
        URLRouter(
            userpanel.routing.websocket_urlpatterns
        )
    ),
})
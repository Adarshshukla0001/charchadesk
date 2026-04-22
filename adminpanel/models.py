from django.db import models

class AdminUser(models.Model):
    admin_id = models.CharField(max_length=50, unique=True)
    password = models.CharField(max_length=255)

    def __str__(self):
        return self.admin_id
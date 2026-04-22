from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('userpanel', '0007_blockeduser'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='edited_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

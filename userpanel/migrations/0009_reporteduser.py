from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('userpanel', '0008_message_edited_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReportedUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reported', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reported_by_users', to='userpanel.user')),
                ('reporter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reported_users', to='userpanel.user')),
            ],
            options={
                'unique_together': {('reporter', 'reported')},
            },
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("settings", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="QueueDisplayMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("queue_system_name", models.CharField(max_length=128, unique=True, verbose_name="Системное имя очереди")),
                ("queue_display_name", models.CharField(max_length=255, verbose_name="Отображаемое имя очереди")),
            ],
            options={
                "verbose_name": "Маппинг очереди",
                "verbose_name_plural": "Маппинг очередей",
                "ordering": ["queue_system_name"],
            },
        ),
        migrations.CreateModel(
            name="AgentDisplayMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("agent_system_name", models.CharField(max_length=128, unique=True, verbose_name="Системное имя оператора")),
                ("agent_display_name", models.CharField(max_length=255, verbose_name="Отображаемое имя оператора")),
            ],
            options={
                "verbose_name": "Маппинг оператора",
                "verbose_name_plural": "Маппинг операторов",
                "ordering": ["agent_system_name"],
            },
        ),
    ]

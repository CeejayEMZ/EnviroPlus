from django.apps import AppConfig


class AppenvironodeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'AppEnviroNode'
    
    def ready(self):
        import AppEnviroNode.signals

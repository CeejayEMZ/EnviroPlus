from django.core.management.base import BaseCommand
from AppEnviroNode.models import SensorNode, SensorNodeAPIKey


class Command(BaseCommand):
    help = 'Generate or regenerate API keys for sensor nodes (Security Fix: Issue 2.1)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Generate API keys for all nodes without existing keys'
        )
        parser.add_argument(
            '--regenerate',
            action='store_true',
            help='Regenerate ALL API keys (destructive)'
        )
        parser.add_argument(
            '--node-id',
            type=int,
            help='Generate API key for specific node ID'
        )

    def handle(self, *args, **options):
        if options['regenerate']:
            if not self._confirm("This will invalidate all existing API keys. Continue?"):
                return
            SensorNodeAPIKey.objects.all().delete()
            options['all'] = True

        if options['all']:
            self._generate_for_all()
        elif options['node_id']:
            self._generate_for_node(options['node_id'])
        else:
            self.stdout.write(
                self.style.WARNING('No action specified. Use --all, --node-id, or --regenerate')
            )

    def _confirm(self, msg):
        resp = input(f"\n⚠️  {msg} (y/N): ").strip().lower()
        return resp == 'y'

    def _generate_for_all(self):
        nodes = SensorNode.objects.all()
        created = 0
        existing = 0

        for node in nodes:
            if hasattr(node, 'api_key'):
                self.stdout.write(f"⏭️  {node.name}: API key already exists")
                existing += 1
            else:
                api_key_obj = SensorNodeAPIKey.objects.create(node=node)
                self.stdout.write(
                    self.style.SUCCESS(f"✅ {node.name}: API key generated")
                )
                self.stdout.write(f"   Key (save this): {api_key_obj.api_key}")
                created += 1

        self.stdout.write(
            self.style.SUCCESS(f"\n✅ Done! Created: {created}, Already existed: {existing}")
        )

    def _generate_for_node(self, node_id):
        try:
            node = SensorNode.objects.get(id=node_id)
            if hasattr(node, 'api_key'):
                api_key_obj = node.api_key
                self.stdout.write(f"⚠️  Node already has API key: {api_key_obj.api_key}")
            else:
                api_key_obj = SensorNodeAPIKey.objects.create(node=node)
                self.stdout.write(
                    self.style.SUCCESS(f"✅ API key generated for {node.name}")
                )
                self.stdout.write(f"\n🔑 API Key (save this): {api_key_obj.api_key}")
                self.stdout.write(
                    f"\n📝 Add to ESP8266 firmware:\n"
                    f"   const char* API_KEY = \"{api_key_obj.api_key}\";"
                )
        except SensorNode.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ Node with ID {node_id} not found"))

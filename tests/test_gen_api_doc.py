"""Regressions for links in the generated public API reference."""

import re
import unittest

from scripts import gen_api_doc as generator


class ApiDocLinksTest(unittest.TestCase):
    def test_repeated_fields_link_to_their_own_class(self):
        for name in generator.CLASS_NAMES:
            cls = getattr(generator.sdk, name)
            if not generator.is_dataclass_type(cls):
                continue
            rendered = generator.render_dataclass(name)
            for field in generator.dataclasses.fields(cls):
                heading = f"{name}.{field.name}"
                target = (name + field.name).lower()
                self.assertIn(f"[`{field.name}`](#{target})", rendered)
                self.assertIn(f"#### {heading}\n", rendered)

    def test_field_targets_are_unique_across_the_document(self):
        document = generator.render_document()
        targets = re.findall(r"\]\(#([\w-]+)\)", document)
        headings = re.findall(r"^#+ (.+)$", document, re.MULTILINE)
        # ASCII API identifiers retain underscores; dots are punctuation removed
        # by the renderer. The docs repository also tests the actual renderer.
        slugs = [heading.replace('`', '').replace('.', '').lower().replace(' ', '-')
                 for heading in headings]
        for target in targets:
            self.assertEqual(slugs.count(target), 1, target)

    def test_constructor_identifier_is_literal_markdown(self):
        document = generator.render_client_class()
        self.assertIn('#### `__init__`\n', document)
        self.assertIn('[`__init__`](#__init__)', document)

    def test_color_migration_note_survives_generation(self):
        document = generator.render_document()
        self.assertIn('**Migrating the display-color type name**', document)
        self.assertIn('`LedColor.Green` to `DeviceColor.Green`', document)
        self.assertIn('Serialized enum values retain the `LedColor` identity', document)


if __name__ == '__main__':
    unittest.main()

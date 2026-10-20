from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import test_work_cli as fixtures
cli=fixtures.WORK_CLI
import designs


class ChoiceTest(unittest.TestCase):
    def test_catalog_discovers_independent_card_and_rejects_path_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card = designs.get('stage-full')
            card['id'] = 'custom-english'
            (root / card['id']).mkdir()
            (root / card['id'] / 'design.json').write_text(json.dumps(card))
            with patch.object(designs, 'CARD_DIR', root):
                self.assertEqual(['custom-english'], list(designs.catalog()))
                self.assertEqual(card, designs.require('custom-english'))
                with self.assertRaisesRegex(designs.DesignError, 'Invalid design identity'):
                    designs.require('../english')

    def test_plan_uses_its_frozen_card_and_generic_mechanism_mode(self):
        import director_plan
        import lines
        card = designs.get('stage-full')
        card.update(id='independent-collage', version=7)
        metadata = {'line': {'id': card['id'], 'version': 7},
                    'design_snapshot': card, 'design_sha256': lines.card_digest(card)}
        parsed = director_plan.parse('## 导演 Brief\n**参考机制：** persistent-anchor\n', metadata, {})
        self.assertFalse(any(item['kind'] == 'mechanism_line_mismatch' for item in parsed['findings']))
        metadata['design_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            director_plan.parse('', metadata, {})

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        shutil.copytree(fixtures.REPO/'.studio/templates',self.root/'.studio/templates')
        cli.account_service(self.root).put('series','series',{'name':'S'})
        cli.account_service(self.root).put('account','a',{'name':'A'})
    def invoke(self,*args,code=0):
        with redirect_stdout(io.StringIO()) as out,redirect_stderr(io.StringIO()) as error:
            self.assertEqual(code,cli.main(['--json',*args],root=self.root),error.getvalue())
        return out.getvalue().strip() or error.getvalue()
    def new(self,title,*args,code=0):
        return self.invoke('new',title,'--workflow','hyperframes_video','--purpose','standard','--series','series',*args,code=code)
    @unittest.skipUnless((fixtures.REPO / '.studio/designs/collage/design.json').is_file(), 'Personal collage card not installed')
    def test_collage_plan_refresh_freezes_compatible_seed(self):
        identity = self.new('mechanism', '--no-account', '--design', 'collage')
        work, _ = cli.locate_work(self.root, identity)
        variant = work / 'variants/variant1'
        plan = variant / 'ANIMATION_PLAN.md'
        metadata = cli.read_frontmatter(plan)
        plan.write_text('---\n' + json.dumps(metadata) + '\n---\n## 导演 Brief\n**参考机制：** persistent-anchor\n## 分镜表\n| S01·A1 | 标题 | 标题 | 说明 | | | |\n## S01\n')
        result = json.loads(self.invoke('--work', identity, '--variant', 'variant1', 'plan', 'refresh'))
        self.assertEqual('variant1', result['variant'])
        self.assertTrue(cli.read_frontmatter(plan)['reference_memory_sha256'])
        state = cli.read_json(variant / 'variant.yaml')
        _, _, findings = cli.visual_memory.resolve(self.root, plan.read_text(), 'collage',
            cli.effective_settings(self.root, state), card=cli.lines.frozen(state))
        self.assertFalse(any(item['kind'] == 'mechanism_line_mismatch' for item in findings))

    def test_explicit_none_and_numbered_variants(self):
        self.assertIn('No design',self.new('missing','--no-account',code=2))
        self.assertIn('Account is not selected',self.new('missing','--design','stage-light',code=2))
        work_id=self.new('first','--no-account','--design','stage-light')
        work,_=cli.locate_work(self.root,work_id)
        state=cli.read_json(work/'variants/variant1/variant.yaml')
        self.assertEqual('none',state['account_selection'])
        self.assertEqual('variant2',self.invoke('variant','add','--no-account','--design','stage-full'))
        self.assertEqual(2,len(cli.variant_paths(work)))
        self.assertIn('multiple account/design',self.new('ambiguous','--variant-id','variant1',code=2))
    def test_new_variant_uses_live_card_and_preserves_adopted_account(self):
        cli.account_service(self.root).put('account','a',{'name':'A','overrides':{'sfx':{'enabled':False}}})
        first=self.new('first','--account','a','--design','stage-light')
        work,_=cli.locate_work(self.root,first)
        prior=cli.read_json(work/'variants/variant1/variant.yaml')
        cli.account_service(self.root).put('account','a',{'name':'A changed','overrides':{'sfx':{'enabled':True}}})
        latest=designs.get('stage-light');latest['version']+=1;latest['defaults']['sfx']['enabled']=True
        real=designs._read
        with patch.object(designs,'_read',side_effect=lambda identity:latest if identity=='stage-light' else real(identity)):
            second=self.new('second','--variant-id','variant1')
            second_work,_=cli.locate_work(self.root,second)
            current=cli.read_json(second_work/'variants/variant1/variant.yaml')
        self.assertNotIn('design_snapshot', prior)
        self.assertNotIn('design_sha256', current)
        self.assertEqual(latest['version'], current['design_version'])
        self.assertEqual(prior['account_revision'],current['account_revision'])
        self.assertFalse(current['sfx']['enabled'])
        self.assertEqual(first,current['selection_source_work'])

    def test_reselect_preserves_sources_and_history_and_retry_is_idempotent(self):
        identity = self.new('first', '--no-account', '--design', 'stage-light')
        work, _ = cli.locate_work(self.root, identity)
        variant = work / 'variants/variant1'
        before = (variant / 'ANIMATION_PLAN.md').read_bytes()
        state = cli.read_json(variant / 'variant.yaml')
        state.update(accepted_preview='draft-1', current_final='final-1')
        cli.write_variant(variant, state)
        recipe = self.root / 'overrides.json'
        recipe.write_text(json.dumps({'sfx': {'enabled': False}, 'seed': 0}))
        args = ('--work', identity, '--variant', 'variant1', 'variant', 'reselect',
                '--design', 'stage-full', '--overrides', str(recipe))
        self.assertEqual('preview', json.loads(self.invoke(*args))['status'])
        self.assertEqual('stage-light', cli.read_json(variant / 'variant.yaml')['design'])
        self.assertEqual('reselected', json.loads(self.invoke(*args, '--apply'))['status'])
        adopted = cli.read_json(variant / 'variant.yaml')
        self.assertEqual('none', adopted['account_selection'])
        self.assertEqual(0, adopted['design_values']['seed'])
        self.assertFalse(adopted['design_values']['sfx.enabled'])
        self.assertIsNone(adopted['accepted_preview'])
        self.assertEqual('final-1', adopted['configuration_history'][0]['current_final'])
        self.assertEqual(before, (variant / 'ANIMATION_PLAN.md').read_bytes())
        self.assertEqual('unchanged', json.loads(self.invoke(*args, '--apply'))['status'])
        self.assertEqual(1, len(cli.read_json(variant / 'variant.yaml')['configuration_history']))


if __name__=='__main__':unittest.main()

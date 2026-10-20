import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.studio'))
import cover


class CoverTest(unittest.TestCase):
    def test_title_change_reuses_assets_and_keeps_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);font=root/'font.ttf';logo=root/'logo.svg';video=root/'final.mp4'
            font.write_bytes(b'font fixture');logo.write_text('<svg/>');video.write_bytes(b'video')
            ref=lambda p:{'path':str(p),'sha256':cover.digest(p.read_bytes())}
            recipe={'width':640,'height':360,'font':ref(font),'logo':ref(logo)}
            def screenshot(command,**kwargs): (Path(command[2])/'cover.png').write_bytes(b'PNG fixture')
            with patch.object(cover.subprocess,'run',side_effect=screenshot) as run:
                first=cover.render(root,'first',recipe)
                self.assertEqual(first,cover.render(root,'first',recipe))
                second=cover.render(root,'second',recipe)
                self.assertEqual(run.call_count,2)
            self.assertNotEqual(first['id'],second['id'])
            self.assertEqual(first['files']['font.ttf'],second['files']['font.ttf'])
            self.assertEqual(video.read_bytes(),b'video')
            with self.assertRaises(ValueError): cover.render(root,'third',{**recipe,'font':{'path':str(font),'sha256':'wrong'}})

    def test_layout_cover_composes_style_character_title_and_tagline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);font=root/'font.ttf';hero=root/'hero.png'
            font.write_bytes(b'font fixture');hero.write_bytes(b'png fixture')
            ref=lambda p:{'path':str(p),'sha256':cover.digest(p.read_bytes())}
            recipe={'width':1080,'height':1440,'font':ref(font),'layout':'character-bottom','character':ref(hero),
                    'background_color':'#101820','color':'#f5f0e6'}
            def screenshot(command,**kwargs): (Path(command[2])/'cover.png').write_bytes(b'PNG fixture')
            with patch.object(cover.subprocess,'run',side_effect=screenshot):
                first=cover.render(root,'标题',recipe,tagline='一句话')
                other=cover.render(root,'标题',recipe,tagline='另一句')
            self.assertNotEqual(first['id'],other['id'])
            self.assertIn('character.png',first['files'])
            page=(Path(first['path'])/'index.html').read_text(encoding='utf-8')
            self.assertIn('<p class="tagline">一句话</p>',page)
            self.assertNotIn('class="logo"',page)
            for bad,message in (({},'tagline'),({'tagline':'x','recipe':{**recipe,'layout':'grid'}},'layout'),
                                ({'tagline':'x','recipe':{k:v for k,v in recipe.items() if k!='character'}},'character')):
                with self.subTest(message=message),self.assertRaisesRegex(ValueError,message):
                    cover.render(root,'标题',bad.get('recipe',recipe),tagline=bad.get('tagline'))
            with self.assertRaisesRegex(ValueError,'Logo'):
                cover.render(root,'legacy',{'width':640,'height':360,'font':ref(font)})


if __name__=='__main__':unittest.main()

class CoverCliTest(unittest.TestCase):
    def test_account_recipe_and_cover_only_export_keep_video(self):
        import test_work_cli as fixtures
        from contextlib import redirect_stdout
        import io, json
        cli=fixtures.WORK_CLI
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            import shutil
            shutil.copytree(fixtures.REPO/'.studio/templates',root/'.studio/templates')
            font=root/'font.ttf';font.write_bytes(b'font')
            logo=root/'logo.svg';logo.write_text('<svg/>')
            ref=lambda p:{'path':str(p),'sha256':cover.digest(p.read_bytes())}
            cli.account_service(root).put('account','account',{'name':'A','overrides':{'cover':{'width':640,'height':360,'font':ref(font),'logo':ref(logo)}}})
            cli.account_service(root).put('series','series',{'name':'S','design':'stage-full'})
            def invoke(*args):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(0,cli.main(['--json',*args],root=root))
                return output.getvalue().strip()
            identity=invoke('new','Cover','--workflow','hyperframes_video','--purpose','standard','--series','series','--account','account','--design','stage-full','--variant-id','main')
            work,_=cli.locate_work(root,identity);variant=work/'variants/main'
            video=variant/'final/final.mp4';video.parent.mkdir();video.write_bytes(b'video unchanged')
            def screenshot(command,**kwargs):
                (Path(command[2])/'cover.png').write_bytes((Path(command[2])/'index.html').read_bytes())
            with patch.object(cover.subprocess,'run',side_effect=screenshot):
                first=json.loads(invoke('cover','render','--title','First'))
                exported=json.loads(invoke('cover','export'))
                second=json.loads(invoke('cover','render','--title','Second'))
                again=json.loads(invoke('cover','export'))
            self.assertNotEqual(first['id'],second['id'])
            self.assertEqual(1,exported['version']);self.assertEqual(2,again['version'])
            self.assertEqual(b'video unchanged',video.read_bytes())
            self.assertEqual(str(root/'exports'/'account'/'series'),exported['directory'])
            self.assertEqual('series_E001_account_v02.png',again['files']['cover'])
            self.assertEqual(['series_E001_account_v01.png'],[p.name for p in Path(exported['directory']).glob('_superseded/*.png')])
            self.assertEqual(1,len(list(Path(exported['directory']).glob('*.png'))))
            # The old <series>/<Work>/<Variant>/ shelf migrates into the same package, keeping the new export current.
            legacy=root/'exports'/'series'/identity/'main'
            legacy.mkdir(parents=True)
            (legacy/'main-r001-e001-cover.png').write_bytes(b'legacy cover')
            (legacy/'.exports.json').write_text(json.dumps([{'sequence':1,'revision':1,'hashes':{'cover':cover.digest(b'legacy cover')},
                                                             'files':{'cover':'main-r001-e001-cover.png'}}]))
            preview=json.loads(invoke('exports','migrate'))
            self.assertEqual([],preview['planned'])
            self.assertIn('already has a new export',preview['skipped'][0]['reason'])
            (Path(second['path'])/'cover.png').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'changed'): cover.verify(Path(second['path']))

    def test_old_shelf_migrates_into_account_series_packages(self):
        import test_work_cli as fixtures
        from contextlib import redirect_stdout
        import io, json, shutil
        cli=fixtures.WORK_CLI
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shutil.copytree(fixtures.REPO/'.studio/templates',root/'.studio/templates')
            font=root/'font.ttf';font.write_bytes(b'font')
            cli.account_service(root).put('account','acct',{'name':'账号A','overrides':{'cover':{'width':640,'height':360,
                'font':{'path':str(font),'sha256':cover.digest(b'font')},'logo':{'path':str(font),'sha256':cover.digest(b'font')}}}})
            cli.account_service(root).put('series','eng',{'name':'英语歪理','design':'stage-full'})
            def invoke(*args):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(0,cli.main(['--json',*args],root=root))
                return json.loads(output.getvalue())
            with redirect_stdout(io.StringIO()) as output:
                cli.main(['new','Old','--workflow','hyperframes_video','--purpose','standard','--series','eng','--account','acct','--design','stage-full','--variant-id','main'],root=root)
            identity=output.getvalue().strip()
            legacy=root/'exports'/'eng'/identity/'main'
            legacy.mkdir(parents=True)
            entries=[]
            for sequence,content in ((1,b'old video'),(2,b'newer video')):
                name=f'main-r00{sequence}-e00{sequence}-video.mp4'
                (legacy/name).write_bytes(content)
                entries.append({'sequence':sequence,'revision':sequence,'hashes':{'video':cover.digest(content)},'files':{'video':name}})
            (legacy/'.exports.json').write_text(json.dumps(entries))
            stray=root/'exports'/'eng'/'work-gone'/'main';stray.mkdir(parents=True);(stray/'.exports.json').write_text('[]')
            (root/'exports'/'eng'/'work-gone'/'x').mkdir();(root/'exports'/'eng'/'work-gone'/'x'/'.exports.json').write_text(json.dumps(entries[:1]))
            preview=invoke('exports','migrate')
            self.assertEqual(['acct/eng/eng_E001_acct']*2,[item['target'] for item in preview['planned']])
            self.assertIn('Unknown work',preview['skipped'][0]['reason'])
            self.assertFalse((root/'exports'/'acct').exists())
            invoke('exports','migrate','--apply')
            folder=root/'exports'/'acct'/'eng'
            self.assertEqual(b'newer video',(folder/'eng_E001_acct_v02.mp4').read_bytes())
            self.assertEqual(b'old video',(folder/'_superseded'/'eng_E001_acct_v01.mp4').read_bytes())
            import csv
            rows=list(csv.DictReader(io.StringIO((root/'exports'/'publish-log.csv').read_text(encoding='utf-8-sig'))))
            self.assertEqual([('eng_E001_acct','账号A','英语歪理','1','2','eng_E001_acct_v02.mp4','待发')],
                             [(r['编号'],r['账号'],r['系列'],r['期数'],r['版本'],r['视频'],r['状态']) for r in rows])
            self.assertTrue((legacy/'main-r001-e001-video.mp4').is_file())
            again=invoke('exports','migrate','--apply')
            self.assertEqual([],again['planned'])
            self.assertEqual([],list(folder.glob('*_v03*')))
            self.assertEqual(b'newer video',(folder/'eng_E001_acct_v02.mp4').read_bytes())

    def test_account_character_library_and_tagline_reach_the_layout_cover(self):
        import test_work_cli as fixtures
        from contextlib import redirect_stdout, redirect_stderr
        import io, json, shutil
        cli=fixtures.WORK_CLI
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shutil.copytree(fixtures.REPO/'.studio/templates',root/'.studio/templates')
            font=root/'font.ttf';font.write_bytes(b'font')
            calm=root/'calm.png';calm.write_bytes(b'calm');grin=root/'grin.png';grin.write_bytes(b'grin')
            ref=lambda p:{'path':str(p),'sha256':cover.digest(p.read_bytes())}
            cli.account_service(root).put('account','account',{'name':'A','overrides':{'cover':{
                'width':1080,'height':1440,'font':ref(font),'layout':'character-bottom',
                'characters':{'calm':ref(calm),'grin':ref(grin)}}}})
            cli.account_service(root).put('series','series',{'name':'S','design':'stage-full'})
            def invoke(*args,status=0):
                with redirect_stdout(io.StringIO()) as output,redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(status,cli.main(['--json',*args],root=root),errors.getvalue())
                return output.getvalue().strip() if status==0 else errors.getvalue()
            identity=invoke('new','Cover','--workflow','hyperframes_video','--purpose','standard','--series','series','--account','account','--design','stage-full','--variant-id','main')
            work,_=cli.locate_work(root,identity);variant=work/'variants/main'
            def screenshot(command,**kwargs):
                (Path(command[2])/'cover.png').write_bytes((Path(command[2])/'index.html').read_bytes())
            with patch.object(cover.subprocess,'run',side_effect=screenshot):
                self.assertIn('--character',invoke('cover','render','--title','T','--tagline','S',status=2))
                self.assertIn('Unknown cover character',invoke('cover','render','--title','T','--tagline','S','--character','nope',status=2))
                first=json.loads(invoke('cover','render','--title','标题','--tagline','一句话','--character','grin'))
                again=json.loads(invoke('cover','render','--title','标题'))
            self.assertEqual(first['id'],again['id'])
            self.assertEqual(cover.digest(grin.read_bytes()),first['files']['character.png'])
            state=cli.read_json(variant/'variant.yaml')
            self.assertEqual(('grin','一句话'),(state['cover_character'],state['cover_tagline']))

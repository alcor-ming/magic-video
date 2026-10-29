// Set HYPERFRAMES_CLI (runtime hyperframes CLI, supplies puppeteer-core) and CHROME_PATH; TEST_CHINESE_FONT optional.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root = await fs.mkdtemp(path.join(os.tmpdir(), 'embedded-texts-'));
try {
  await fs.mkdir(path.join(root, 'runtime'));
  for (const name of ['appearance.js','broll.js']) await fs.copyFile('.studio/runtime/' + name, path.join(root,'runtime',name));
  await fs.copyFile(process.env.TEST_CHINESE_FONT || '/usr/share/fonts/opentype/unifont/unifont.otf', path.join(root, 'font.otf'));
  const lock = {schema_version:1, resolver_version:1, contract_version:1, assets:[], ratio:'16:9',
    capabilities:{bindings:{theme:'optional',background:'optional'}}, selection:{theme:null,background:null,motion:{}},
    parameters:{theme:{},background:{},motion:{}}, card_fonts:{fonts:[{family:'CardFont',path:'font.otf',license:'LICENSE'}]}};
  await fs.writeFile(path.join(root,'appearance-lock.json'), JSON.stringify(lock));
  await fs.writeFile(path.join(root,'LICENSE'), 'Synthetic test uses the system fixture font; no font redistribution.');
  const write = async (text, wrongFont=false) => fs.writeFile(path.join(root,'index.html'), `<!doctype html><div id="S01"><div id="stage" data-hf-layer="stage"><canvas width="400" height="200"></canvas></div></div>
<script src="runtime/appearance.js"></script><script src="runtime/broll.js"></script><script>
window.__example={ready:(async()=>{const appearance=await HarnessAppearance.load();const stage=document.getElementById('stage');
appearance.theme={tokens:{typography:{heading:'UninstalledTheme'}}};HarnessAppearance.apply(stage,appearance);
if(!stage.style.getPropertyValue('--appearance-typography-heading').includes('HarnessFont_')) throw Error('Theme heading did not adopt card font');
window.binding=await HarnessBroll.mount({id:'synthetic',text_ownership:{mode:'embedded',kinds:['title']},broll:{duration:{min:1,max:10,default:2},timing:'stretch',caption_safe_zone:{'16:9':{}},slots:{},params:{},sfx_cues:[]}},
 {stage,appearance,startCue:0,endCue:2},async()=>({events:[],texts:()=>[{id:'title',text:${JSON.stringify(text)},start:0,end:2,kind:'independent',embedded:true,text_type:'title'}],renderAt:t=>{const c=stage.querySelector('canvas').getContext('2d');c.clearRect(0,0,400,200);c.font='32px '+(${wrongFont}?'sans-serif':appearance.fontFamily);c.fillText(${JSON.stringify(text)},5,45);}}));})()};
</script>`);
  const request = path.join(root,'request.json');
  await fs.writeFile(request, JSON.stringify({project:root,scenes:[{id:'S01',start:0,duration:2}]}));
  const inspect = () => JSON.parse(execFileSync(process.execPath, ['.studio/text_inventory.mjs',request], {encoding:'utf8'}));
  await write('增长 30%');
  const first = inspect();
  assert.equal(first.complete,true); assert.equal(first.items.length,1);
  assert.equal(first.items[0].font_coverage,true); assert.equal(first.items[0].ownership_allowed,true);
  assert.equal(first.items[0].scene,'S01'); assert.equal(first.items[0].text,'增长 30%');
  await write('增长 30%',true);
  assert.equal(inspect().items[0].font_coverage,false,'Canvas actual font must match its frozen font probe');
  await fs.copyFile('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', path.join(root, 'font.otf'));
  await write('missing 龘');
  assert.equal(inspect().items[0].font_coverage,false);
  console.log('embedded inventory, card-font mapping and real missing-glyph detection passed');
} finally { await fs.rm(root,{recursive:true,force:true}); }

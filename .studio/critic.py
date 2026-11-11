"""Read-only evidence packages and validated advisory verdicts; no model API."""
import hashlib
import html
import json
import math
from pathlib import Path


def pending_issues(rounds):
    issues = {}
    for entry in rounds:
        verdict = entry.get('verdict', {})
        for update in verdict.get('previous', []):
            if update['status'] == 'FIXED':
                issues.pop(update['id'], None)
        for item in verdict.get('new_issues', []):
            issues[item['id']] = item
    return list(issues.values())


def validate_verdict(value, entry):
    required = {'round', 'draft_id', 'snapshot_sha256', 'new_issues', 'previous'}
    if entry.get('reference_ids'):
        required.add('references')
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Verdict requires round, draft_id, snapshot_sha256, new_issues and previous')
    if any(value[key] != entry[key] or type(value[key]) is not type(entry[key]) for key in ('round', 'draft_id', 'snapshot_sha256')):
        raise ValueError('Verdict targets another round or snapshot')
    if not isinstance(value['new_issues'], list) or not isinstance(value['previous'], list):
        raise ValueError('Verdict issue lists must be arrays')
    seen = set()
    for item in value['new_issues']:
        if (not isinstance(item, dict) or not {'id', 'description'} <= item.keys()
                or set(item) - {'id', 'description', 'scene', 'time', 'severity'}
                or any(not isinstance(item[key], str) or not item[key].strip() for key in ('id', 'description'))
                or item['id'] in seen or item['id'] in entry.get('historical_issue_ids', [])):
            raise ValueError('New issues require unique IDs and descriptions')
        if 'time' in item and (type(item['time']) not in (int, float) or not 0 <= item['time'] < float('inf')):
            raise ValueError('Issue time must be finite and nonnegative')
        seen.add(item['id'])
    seen = set()
    for item in value['previous']:
        if (not isinstance(item, dict) or set(item) != {'id', 'status', 'detail'}
                or not isinstance(item['id'], str) or item['id'] in seen
                or item['status'] not in ('FIXED', 'PARTLY', 'STILL')
                or not isinstance(item['detail'], str) or not item['detail'].strip()):
            raise ValueError('Previous issues require unique IDs, FIXED/PARTLY/STILL and detail')
        seen.add(item['id'])
    if seen != {item['id'] for item in entry['previous_issues']}:
        raise ValueError('Verdict must address every previous unresolved issue')
    if entry.get('reference_ids'):
        seen = set()
        if not isinstance(value['references'], list):
            raise ValueError('Reference verdicts must be an array')
        for item in value['references']:
            if (not isinstance(item, dict) or set(item) != {'id', 'status', 'detail'}
                    or not isinstance(item['id'], str) or item['id'] in seen
                    or item['status'] not in ('达到', '部分', '未达')
                    or not isinstance(item['detail'], str) or not item['detail'].strip()):
                raise ValueError('Invalid reference dimension verdict')
            seen.add(item['id'])
        if seen != set(entry['reference_ids']):
            raise ValueError('Verdict must address every reference dimension exactly once')
    return value


def hashes(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Invalid critic package directory')
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Critic package cannot contain symlinks')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def package(directory, report, direction, previous, entry):
    from PIL import Image, ImageDraw
    shots = [sample for sample in report['samples'] if sample.get('ready') and sample.get('screenshot')]
    if report['status'] != 'diagnostic_only' or not shots:
        raise ValueError('Critic requires current, sampled PNG evidence')
    for sample in shots:
        name = sample['screenshot']
        if Path(name).name != name or Path(name).suffix != '.png':
            raise ValueError('Invalid screenshot path')
    (directory / 'measurements.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (directory / 'direction.json').write_text(json.dumps(direction, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (directory / 'previous.json').write_text(json.dumps(previous, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tiles = []
    # ponytail: at most 80 thumbnails on the sheet; all frames remain in the HTML viewer.
    for sample in shots[::max(1, (len(shots) + 79) // 80)]:
        with Image.open(directory / 'images' / sample['screenshot']) as image:
            image = image.convert('RGB'); image.thumbnail((240, 135))
            tile = Image.new('RGB', (240, 158), 'white'); tile.paste(image, (0, 0))
            ImageDraw.Draw(tile).text((4, 140), f"{sample['time']:.3f}s", fill='black')
            tiles.append(tile)
    sheet = Image.new('RGB', (960, 158 * ((len(tiles) + 3) // 4)), 'white')
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % 4) * 240, (i // 4) * 158))
    sheet.save(directory / 'contact-sheet.png')
    tiles = []
    for sample in sorted(shots, key=lambda sample: sample['time']):
        with Image.open(directory / 'images' / sample['screenshot']) as image:
            image = image.convert('RGB'); image = image.resize((480, round(image.height * 480 / image.width)))
            tile = Image.new('RGB', (480, image.height + 23), 'white'); tile.paste(image, (0, 0))
            ImageDraw.Draw(tile).text((4, image.height + 5), f"{sample['time']:.3f}s", fill='black')
            tiles.append(tile)
    height = max(tile.height for tile in tiles)
    sheet = Image.new('RGB', (1920, height * ((len(tiles) + 3) // 4)), 'white')
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % 4) * 480, (i // 4) * height))
    sheet.save(directory / 'feed-sheet.png')
    figures = ''.join(f'<figure><img loading="lazy" src="images/{html.escape(s["screenshot"], quote=True)}" alt="Frame at {s["time"]:.3f} seconds"><figcaption>{s["time"]:.3f}s</figcaption></figure>' for s in shots)
    strips = []
    for boundary in report.get('boundaries', []):
        selected = [s for s in shots if any(abs(s['time'] - max(0, boundary + offset)) < .00001 for offset in (-.2, -.1, 0, .1, .2, .4))]
        strips.append({'boundary': boundary, 'frames': [{'time': s['time'], 'path': 'images/' + s['screenshot']} for s in selected]})
    (directory / 'strips.json').write_text(json.dumps(strips, indent=2) + '\n', encoding='utf-8')
    fps = report.get('fps') or 60
    pairs = []
    for boundary in report.get('boundaries', []):
        if boundary <= 0:
            continue
        first = math.ceil(boundary * fps - 1e-7) / fps
        frames = [next(({'time': s['time'], 'path': 'images/' + s['screenshot']} for s in shots
                        if abs(s['time'] - at) < .00001 and abs(s.get('actual_time', s['time']) - at) < .00001), None)
                  for at in (max(0, first - 1 / fps), first)]
        pairs.append({'boundary': boundary, 'before': frames[0], 'after': frames[1],
                      'status': 'sampled' if all(frames) else 'unmeasured'})
    (directory / 'boundary-pairs.json').write_text(json.dumps(pairs, indent=2) + '\n', encoding='utf-8')
    (directory / 'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Draft 逐帧评审</title><style>body{font:16px sans-serif;margin:24px}main{display:flex;flex-wrap:wrap;gap:12px}figure{margin:0}img{width:320px;height:auto}</style><h1>Draft 逐帧评审</h1><p>只读证据；不代表接受。时间标记单位为秒。</p><a href="contact-sheet.png">Contact sheet</a> <a href="feed-sheet.png">feed-sheet.png</a><p>480 px 宽约等于手机信息流里的实际大小；在这张图上读不出的字和脸，手机上也读不出</p><main>' + figures + '</main></html>', encoding='utf-8')
    if entry['settings']['critic.provider']['value'] != 'off':
        prompt = ('只读本包的 direction.json、measurements.json、previous.json、strips.json 与全部相关 PNG，'
                  '不得读取制作过程或修改源。必须实际看图，不能用文本检查代替；模型名只记录来源，不证明看图能力；缺实际图像读取或人工观看证据时报告未验证，不用自述代替。'
                  '核对主体与次级响应、阅读保护、错相、静止及延续；帧图不能证明声音或完整动态。'
                  '对 previous.json 每个问题逐项给 FIXED / PARTLY / STILL 和证据。结论只作建议，不代替用户接受。\n'
                  '输出严格 JSON：' + json.dumps({key: entry[key] for key in ('round', 'draft_id', 'snapshot_sha256')}, ensure_ascii=False)[:-1]
                  + ', "new_issues":[{"id":"unique-id","description":"问题及帧证据"}], "previous":[{"id":"existing-id","status":"FIXED|PARTLY|STILL","detail":"帧证据"}]}\n')
        if (directory / 'memory.json').is_file():
            prompt += ('读取 memory.json：先核对 profile_checks，再逐项核对 known_defects 的描述及证据帧。'
                       '参考帧位于 reference-memory/，只对照每段 reason 限定的借鉴维度，不评相似度、不提名优秀。\n')
        if entry.get('reference_ids'):
            prompt += ('在上述 JSON 增加必填 references 数组，每个引用恰好一次：'
                       + json.dumps([{'id': identity, 'status': '达到|部分|未达', 'detail': '借鉴维度与帧证据'}
                                     for identity in entry['reference_ids']], ensure_ascii=False) + '\n')
        (directory / 'PROMPT.md').write_text(prompt, encoding='utf-8')
    return hashes(directory)

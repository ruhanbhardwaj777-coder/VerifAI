from flask import Flask, request, jsonify, send_from_directory, make_response
import sqlite3, json, os, re, hashlib, urllib.request, urllib.error, urllib.parse, time
from datetime import datetime, timezone

app = Flask(__name__, static_folder='static')

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

@app.route('/api/<path:p>', methods=['OPTIONS'])
def options_handler(p):
    return make_response('', 204)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', 'sk-aHlx5c6BlrcPAJ2s94K2bDTY4s3e4p3DsyKHgJid1eWqJHeO')
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_MODEL = 'claude-haiku-4-5-20251001'

def call_ai(claim, lang='en'):
    lang_name = 'Hindi (Devanagari script, natural conversational Hindi)' if lang == 'hi' else 'English'

    prompt = f'''You are a senior fact-checker at a top investigative newsroom. You are rigorous, precise, and never guess.

LANGUAGE RULE (NON-NEGOTIABLE): Write the "explanation" field in {lang_name}. Keep "verdict", "category", "sources", "related_queries" in English always.

CLAIM TO ANALYZE:
"{claim}"

Reply with ONLY this JSON (no markdown, no backticks, no extra text):
{{"verdict":"<true|false|misleading|insufficient evidence|unverifiable>","explanation":"<3-4 sentences in {lang_name} — direct answer first, then specific evidence with real numbers/dates/org names>","confidence":<integer 0-100>,"category":"<science|history|politics|health|technology|religion|general>","sources":["<1-3 real specific source names>"],"related_queries":["<3 English search queries to verify this>"]}}

VERDICT RULES:
- "true": strongly supported by scientific consensus or verified historical record
- "false": directly contradicted by established evidence, clear myth or misinformation
- "misleading": contains truth but missing critical context or leads to false conclusion
- "insufficient evidence": plausible but lacks authoritative backing
- "unverifiable": opinion, prediction, or not a falsifiable factual claim

CONFIDENCE (be calibrated):
- 95-100: scientific consensus, all major sources agree
- 85-94: strong evidence, well-documented
- 70-84: good evidence but some debate
- 50-69: mixed evidence or significant uncertainty
- below 50: weak, anecdotal, or highly contested

EXPLANATION RULES:
- Lead with the direct verdict and reason
- Cite specific numbers, dates, named organizations or studies
- Never say "experts say" or "studies show" — name them
- If misleading, explain what is true AND what is wrong
- 3-4 sentences max
'''

    payload = json.dumps({
        'model': ANTHROPIC_MODEL,
        'max_tokens': 1024,
        'messages': [{'role': 'user', 'content': prompt}]
    }).encode('utf-8')

    req = urllib.request.Request(
        ANTHROPIC_URL, data=payload,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            raw = data['content'][0]['text']
            clean = raw.replace('```json', '').replace('```', '').strip()
            if not clean.startswith('{'):
                m = re.search(r'\{[\s\S]*\}', clean)
                clean = m.group(0) if m else clean
            result = json.loads(clean)
            result.setdefault('verdict', 'insufficient evidence')
            result.setdefault('explanation', 'No explanation provided.')
            result.setdefault('confidence', 50)
            result.setdefault('category', 'general')
            result.setdefault('sources', [])
            result.setdefault('related_queries', [])
            result['model_used'] = ANTHROPIC_MODEL
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f'Anthropic API error {e.code}: {body[:300]}')
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f'Response parse error: {e}')
    except Exception as e:
        raise RuntimeError(f'Call failed: {type(e).__name__}: {e}')


# ── Database ───────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'facts.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        claim_hash TEXT UNIQUE,
        claim_text TEXT NOT NULL,
        verdict TEXT NOT NULL,
        explanation TEXT NOT NULL,
        confidence INTEGER NOT NULL,
        category TEXT DEFAULT "general",
        sources TEXT DEFAULT "[]",
        related_queries TEXT DEFAULT "[]",
        check_count INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )''')
    conn.commit()
    seed = [
        ("The Great Wall of China is visible from space", "false", "The Great Wall cannot be seen from space with the naked eye. NASA astronauts have confirmed this. The wall is only 15-30 feet wide, far too narrow to spot from orbit.", 97, "science", ["NASA Human Spaceflight", "China National Space Administration"], ["Great Wall visibility from space NASA", "can astronauts see Great Wall orbit", "objects visible from space size limit"], 24),
        ("Humans only use 10% of their brain", "false", "Brain imaging shows virtually all brain regions are active at some point. Most of the brain is active almost all the time, even during sleep.", 99, "science", ["Nature Neuroscience", "Scientific American"], ["brain usage percentage myth debunked", "fMRI brain activity all regions", "10 percent brain myth origin"], 31),
        ("Lightning never strikes the same place twice", "false", "Lightning absolutely strikes the same place repeatedly. The Empire State Building is struck roughly 23 times per year.", 98, "science", ["NOAA", "National Geographic"], ["lightning strikes same place twice myth", "Empire State Building lightning strikes per year", "how lightning chooses where to strike"], 19),
        ("Albert Einstein failed math in school", "false", "Einstein mastered calculus by age 15 and received top marks in mathematics. This myth stems from a misunderstanding of the Swiss grading system.", 95, "history", ["Einstein: His Life and Universe by Walter Isaacson"], ["Einstein school grades history", "Einstein math prodigy evidence", "Einstein failed school myth debunked"], 28),
        ("Napoleon Bonaparte was very short", "misleading", "Napoleon stood around 5ft 7in (170cm), average for a French man of his era. The myth came from British propaganda and confusion between French and English measurement units.", 88, "history", ["Histoires & Civilisations", "Journal of the Royal Society of Medicine"], ["Napoleon Bonaparte actual height historical records", "Napoleon short myth British propaganda", "French inch vs English inch measurement"], 22),
        ("Goldfish have a 3-second memory", "false", "Goldfish can remember things for months. Studies show they can navigate mazes and respond to signals for food.", 96, "science", ["Macquarie University Fish Lab", "Scientific American"], ["goldfish memory span research", "goldfish 3 second memory myth debunked", "fish memory scientific studies"], 17),
        ("The Earth is flat", "false", "The Earth is an oblate spheroid confirmed by satellite imagery, GPS, physics, circumnavigation, and every major space agency.", 100, "science", ["NASA", "ESA", "NOAA"], ["Earth shape scientific evidence", "flat Earth theory debunked", "oblate spheroid proof satellite imagery"], 52),
        ("Vaccines cause autism", "false", "Extensive research across millions of children found no link between vaccines and autism. The 1998 Wakefield study was retracted for data fraud.", 99, "health", ["WHO", "CDC", "Annals of Internal Medicine (2019)"], ["vaccines autism link studies 2019", "Wakefield study retracted fraud", "MMR vaccine autism scientific consensus"], 44),
        ("Coffee stunts your growth", "false", "No scientific evidence shows caffeine stunts height. Height is primarily determined by genetics and nutrition.", 90, "health", ["Harvard Health", "American Journal of Clinical Nutrition"], ["caffeine height growth scientific evidence", "coffee stunts growth myth origin", "factors that affect height growth"], 11),
        ("The universe is approximately 13.8 billion years old", "true", "Based on measurements of the cosmic microwave background by the Planck satellite, scientists estimate the universe is 13.787 billion years old.", 96, "science", ["ESA Planck Mission (2018)", "NASA WMAP Mission"], ["universe age 13.8 billion years evidence", "Planck satellite cosmic microwave background", "how scientists measure universe age"], 9),
        ("Mount Everest is the tallest mountain on Earth", "misleading", "It depends how you measure. Everest has the highest elevation above sea level. But Mauna Kea is taller base-to-peak. Highest and tallest are different measurements.", 92, "science", ["National Geographic", "Royal Geographical Society"], ["Mauna Kea vs Everest height comparison", "tallest vs highest mountain difference", "mountain height measurement methods"], 16),
        ("Cleopatra lived closer in time to the Moon landing than to the Great Pyramid", "true", "The Great Pyramid was built around 2560 BCE. Cleopatra was born around 69 BCE. The Moon landing was 1969 CE, just 2038 years after Cleopatra.", 97, "history", ["Encyclopaedia Britannica", "Oxford Ancient History"], ["Cleopatra timeline vs pyramids vs moon landing", "ancient Egypt timeline historical dates", "Cleopatra birth year historical record"], 18),
    ]
    for item in seed:
        claim_text, verdict, explanation, confidence, category, sources, queries, count = item
        h = hashlib.md5(claim_text.lower().strip().encode()).hexdigest()
        now = now_iso()
        try:
            c.execute('''INSERT OR IGNORE INTO claims
                (claim_hash,claim_text,verdict,explanation,confidence,category,sources,related_queries,check_count,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (h, claim_text, verdict, explanation, confidence, category,
                 json.dumps(sources), json.dumps(queries), count, now, now))
        except Exception:
            pass
    conn.commit()
    conn.close()

STOPWORDS = {'this','that','with','from','have','been','they','were','their','will','when',
             'what','which','about','into','than','then','more','also','some','just','only',
             'both','does','said','each','very','much','many','most','such','same','even'}

def find_match(claim, conn):
    h = hashlib.md5(claim.lower().strip().encode()).hexdigest()
    row = conn.execute('SELECT * FROM claims WHERE claim_hash=?', (h,)).fetchone()
    if row:
        return dict(row)
    words = set(re.findall(r'\b[a-z]{4,}\b', claim.lower())) - STOPWORDS
    if not words:
        return None
    best, best_score = None, 0
    for row in conn.execute('SELECT * FROM claims').fetchall():
        iw = set(re.findall(r'\b[a-z]{4,}\b', row['claim_text'].lower())) - STOPWORDS
        overlap = len(words & iw)
        score = overlap / max(len(words), 1)
        if score > 0.5 and score > best_score:
            best_score = score
            best = dict(row)
    return best

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/check', methods=['POST'])
def check_claim():
    data = request.get_json(silent=True) or {}
    claim = str(data.get('claim', '')).strip()
    lang  = str(data.get('lang', 'en')).strip()[:10]
    if len(claim) < 5:
        return jsonify({'error': 'Claim too short (min 5 characters).'}), 400
    if len(claim) > 1000:
        return jsonify({'error': 'Claim too long (max 1000 characters).'}), 400

    conn = get_db()
    try:
        existing = find_match(claim, conn)
        if existing:
            conn.execute('UPDATE claims SET check_count=check_count+1, updated_at=? WHERE id=?',
                         (now_iso(), existing['id']))
            conn.commit()
            existing['sources'] = json.loads(existing['sources'])
            existing['related_queries'] = json.loads(existing.get('related_queries') or '[]')
            existing['from_db'] = True
            return jsonify(existing)

        try:
            analysis = call_ai(claim, lang)
            analysis['from_ai'] = True
        except Exception as e:
            app.logger.error(f'AI failed: {e}')
            return jsonify({'error': str(e)}), 500

        h = hashlib.md5(claim.lower().strip().encode()).hexdigest()
        now = now_iso()
        conn.execute('''INSERT OR IGNORE INTO claims
            (claim_hash,claim_text,verdict,explanation,confidence,category,sources,related_queries,check_count,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (h, claim, analysis['verdict'], analysis['explanation'],
             analysis['confidence'], analysis['category'],
             json.dumps(analysis.get('sources', [])),
             json.dumps(analysis.get('related_queries', [])),
             1, now, now))
        conn.commit()
        analysis['claim_text'] = claim
        analysis['created_at'] = now
        return jsonify(analysis)
    finally:
        conn.close()

@app.route('/api/history')
def get_history():
    conn = get_db()
    try:
        rows = conn.execute('SELECT * FROM claims ORDER BY updated_at DESC LIMIT 50').fetchall()
        result = [dict(r) for r in rows]
        for d in result:
            d['sources'] = json.loads(d['sources'])
            d['related_queries'] = json.loads(d.get('related_queries') or '[]')
        return jsonify(result)
    finally:
        conn.close()

@app.route('/api/trending')
def get_trending():
    conn = get_db()
    try:
        rows = conn.execute('SELECT * FROM claims ORDER BY check_count DESC LIMIT 12').fetchall()
        result = [dict(r) for r in rows]
        for d in result:
            d['sources'] = json.loads(d['sources'])
            d['related_queries'] = json.loads(d.get('related_queries') or '[]')
        return jsonify(result)
    finally:
        conn.close()

@app.route('/api/stats')
def get_stats():
    conn = get_db()
    try:
        total = conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0]
        verdicts = conn.execute('SELECT verdict, COUNT(*) as c FROM claims GROUP BY verdict').fetchall()
        return jsonify({'total_claims': total, 'verdicts': {r['verdict']: r['c'] for r in verdicts}})
    finally:
        conn.close()
        
if __name__ == '__main__':
    print('\n' + '='*50)
    print('  VerifAI — Multilingual Fact Checker')
    print('='*50)
    init_db()
    print('  DB ready | Models:', len(MODELS), 'with fallback')
    print('  Open: http://localhost:5050')
    print('='*50 + '\n')
    port = int(os.environ.get('PORT', 5050))
    app.run(debug=False, host='0.0.0.0', port=port)

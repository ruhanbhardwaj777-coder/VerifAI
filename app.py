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

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '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')
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'

MODELS = [
    'meta-llama/llama-3.3-70b-instruct:free',
    'google/gemma-3-27b-it:free',
    'google/gemma-3-12b-it:free',
    'mistralai/mistral-7b-instruct:free',
    'deepseek/deepseek-r1-distill-llama-70b:free',
    'qwen/qwen-2.5-72b-instruct:free',
]

def call_ai(claim, lang='en'):
    lang_map = {
        'hi': 'Hindi (Devanagari script only — write exactly as a native Hindi speaker would, natural and conversational)',
        'en': 'English',
    }
    lang_name = lang_map.get(lang, 'English')

    prompt = f'''You are a senior fact-checker at a top investigative newsroom. You are rigorous, precise, and never guess.

LANGUAGE RULE (NON-NEGOTIABLE): Write the "explanation" field in {lang_name}. Do not use any other language for explanation regardless of how the claim is phrased. Keep "verdict", "category", "sources", "related_queries" in English always.

CLAIM TO ANALYZE:
"{claim}"

STEP 1 — Think through this before answering:
- What is the core factual assertion being made?
- What does the scientific/historical consensus say?
- Are there nuances, context, or partial truths?
- How confident can you be given available evidence?

STEP 2 — Reply with ONLY this JSON (no markdown, no backticks, no extra text):
{{"verdict":"<see rules below>","explanation":"<3-4 sentences in {lang_name} — start with the direct answer, then give specific evidence, name actual studies or sources, end with important context if any>","confidence":<see confidence guide below>,"category":"<science|history|politics|health|technology|religion|general>","sources":["<1-3 real, specific source names — e.g. WHO 2023 report, NASA, Nature journal, not vague like 'experts say'>"],"related_queries":["<3 specific English search queries a fact-checker would use to verify this>"]}}

VERDICT RULES:
- "true" — Strongly supported by scientific consensus, verified historical record, or authoritative sources. Example: "The Earth orbits the Sun"
- "false" — Directly contradicted by established evidence. A clear myth or misinformation. Example: "Vaccines cause autism"
- "misleading" — Contains a grain of truth but is missing critical context, cherry-picks data, or leads to a false conclusion. Example: "Napoleon was very short" (average for his era, myth from propaganda)
- "insufficient evidence" — Claim may be plausible but lacks peer-reviewed or authoritative backing. Cannot be confirmed or denied reliably.
- "unverifiable" — Subjective opinion, future prediction, or not a falsifiable factual claim. Example: "This movie is the best ever made"

CONFIDENCE GUIDE (be calibrated, not generous):
- 95-100: Scientific consensus, multiple authoritative sources agree completely
- 85-94: Strong evidence, well-documented, minor uncertainty only
- 70-84: Good evidence but some legitimate debate or missing data
- 50-69: Mixed evidence, conflicting studies, or significant uncertainty
- 30-49: Weak evidence, mostly anecdotal, or strongly contested
- 10-29: Very little evidence, mostly speculation
- Use the FULL range — do not default to 85-95 for everything

EXPLANATION QUALITY RULES:
- Lead with the direct answer (true/false/etc) and why in one sentence
- Cite specific numbers, dates, studies, or named organizations where possible
- Do NOT use vague phrases like "experts say", "studies show", "it is believed"
- If misleading, clearly explain what part is true AND what part is wrong
- Keep it factual, not preachy
- 3-4 sentences max, dense with information
'''


    last_error = None
    for model in MODELS:
        for attempt in range(2):
            try:
                payload = json.dumps({
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0.1,
                    'max_tokens': 800
                }).encode('utf-8')

                req = urllib.request.Request(
                    OPENROUTER_URL, data=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                        'HTTP-Referer': 'http://localhost:5050',
                        'X-Title': 'VerifAI Fact Checker'
                    }
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                    if 'error' in data:
                        raise RuntimeError(f"Model error: {data['error']}")
                    raw = data['choices'][0]['message']['content']
                    if not raw or not raw.strip():
                        raise RuntimeError('Empty response')
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
                    result['model_used'] = model
                    return result

            except urllib.error.HTTPError as e:
                body = e.read().decode()
                last_error = f'{model} HTTP {e.code}: {body[:200]}'
                app.logger.warning(last_error)
                if e.code in (429, 503, 529):
                    time.sleep(1.5)
                break
            except (json.JSONDecodeError, KeyError) as e:
                last_error = f'{model} parse error: {e}'
                app.logger.warning(last_error)
                break
            except Exception as e:
                last_error = f'{model}: {type(e).__name__}: {e}'
                app.logger.warning(last_error)
                if attempt == 0:
                    time.sleep(1)

    raise RuntimeError(f'All models failed. Last: {last_error}')

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
    app.run(debug=False, port=5050)
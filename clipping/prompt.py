"""The single analysis prompt shared by every AI provider.

Kept byte-for-byte in spirit with the reference implementation: clip rules,
viral scoring, hook selection, typography, B-roll, BGM mood, metadata and the
strict JSON contract all live here.
"""

MIN_CLIP_DURATION = 20
MAX_CLIP_DURATION = 179

TARGET_ACCOUNTS = {
    "Business": {
        "akun_tujuan": "Business.Mereska",
        "angle_desc": "Kalau angle-nya bisnis, brand, omzet, jualan, founder, marketing, atau UMKM.",
        "bio": "Insight bisnis, founder story & brand lokal. Business | Founder | Finance | Beauty | Marketing",
    },
    "Life": {
        "akun_tujuan": "Life.Mereska",
        "angle_desc": "Kalau angle-nya personal life, lifestyle, skincare, career, mindset, relationship, personal finance, atau self growth.",
        "bio": "Klip insight buat upgrade hidup & mindset. Podcast | Career | Finance | Beauty | Self Growth",
    },
    "Creator": {
        "akun_tujuan": "Creator.Mereska",
        "angle_desc": "Kalau angle-nya konten digital, AI, affiliate, tools, clipping, monetisasi, atau cara menghasilkan uang dari konten.",
        "bio": "Ngulik konten digital biar bisa jadi uang. AI | Affiliate | Clips | Tools | Monetize",
    },
    "Muslim": {
        "akun_tujuan": "Muslim.Mereska",
        "angle_desc": "Kalau angle-nya religi, rezeki, doa, ibadah, kerja karena Allah, keluarga Islami, atau bisnis dengan nilai Islam.",
        "bio": "Reminder kerja, rezeki & hidup bernilai Islam. Islamic | Rezeki | Family | Work | Business",
    },
}


def _build_account_classification_prompt() -> str:
    lines = []
    for tipe, data in TARGET_ACCOUNTS.items():
        lines.append(f"- {tipe}: {data['angle_desc']}")
        lines.append(f'  (akun_tujuan: "{data["akun_tujuan"]}", bio: "{data["bio"]}")')
    return "\n".join(lines)


def get_analysis_prompt(transkrip_lengkap: str, jumlah_clip: int, durasi_hook: int, cfg=None) -> str:
    """Centralized prompt for Gemini, NVIDIA NIM and vLLM."""
    hook_v2_prompt = ""
    if cfg and getattr(cfg, "hook_v2", False):
        items = getattr(cfg, "hook_v2_items", 3)
        style = getattr(cfg, "hook_v2_style", "controversial_fast_glitch")
        hook_v2_prompt = f"""

HOOK V2 (MULTI-HOOK INTRO — WAJIB):
- Selain hook standar, buat juga "hook_v2" berisi {items} potongan pendek (0.5-2 detik) yang diambil dari momen paling mencolok/controversial/emosional di dalam klip.
- Gaya: {style}
- Setiap item harus berisi: start_time, end_time, dan text (teks on-screen singkat 2-5 kata).
- Item harus diurutkan dari paling kuat ke paling lemah.
- Transisi antar item akan ditambahkan otomatis (white flash / glitch) oleh sistem.
- Isi field "hook_v2" sebagai objek dengan:
  - "enabled": true
  - "items": array dari objek (start_time, end_time, text)
  - "transition": objek dengan "type" ("white_flash" atau "glitch")
"""

    segment_prompt = ""
    if cfg and not getattr(cfg, "no_segment_trim", False):
        silence_hint = ""
        if getattr(cfg, "silence_trim", False):
            silence_hint = "\n- AGRESIF buang bagian diam/silence/dead air. Jangan sertakan jeda lebih dari 0.5 detik."
        segment_prompt = f"""

SEGMENT-BASED TRIMMING (KEEP SEGMENTS — WAJIB):
- Untuk setiap klip, analisis apakah ada bagian yang kurang menarik, terlalu diam, bertele-tele, atau filler di tengah.
- Jika ada, pecah klip menjadi beberapa "keep_segments" — hanya potongan terbaik yang dipertahankan.
- Setiap segment berisi: start_time dan end_time.
- Segment harus berurutan secara kronologis dan tidak boleh overlap.
- Jika seluruh durasi klip sudah padat dan menarik, cukup buat 1 segment yang mencakup seluruh durasi.{silence_hint}
- Isi field "keep_segments" sebagai array dari objek (start_time, end_time).
"""

    return f"""
Kamu adalah Art Director, Editor Video, dan Strategist Metadata Short-Form Content untuk TikTok, Reels, dan YouTube Shorts.

Baca transkrip video berikut. Format transkrip:
[detik_mulai - detik_selesai] teks

TUGAS UTAMA:
- Carikan {jumlah_clip} momen paling menarik, paling kuat, paling shareable, dan paling berpotensi viral untuk dijadikan klip pendek.
- Urutkan klip berdasarkan viral_score tertinggi ke terendah. Peringkat ("rank") hanya sebagai nomor urut (1, 2, 3...).
- Untuk setiap klip, hasilkan timing klip, hook, typography plan, b-roll plan, alasan pemilihan, metadata lintas platform, dan klasifikasi akun tujuan.
- Semua output harus sangat relevan dengan isi klip, bukan isi video penuh secara umum.

ATURAN PEMILIHAN KLIP & VIRAL-BILITY:
- Durasi klip harus {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} detik.
- Pilih bagian yang punya emosi, konflik, kejutan, insight, opini kuat, pelajaran praktis, atau punchline jelas.
- Evaluasi kekuatan viral dan berikan "viral_score" (1-100):
  - 90-100: Sangat berpotensi fyp/viral, emosi/konflik kuat, hook sangat nendang.
  - 80-89: Menarik, berpotensi performa baik.
  - 70-79: Standar, informatif tapi mungkin kurang greget.
- Utamakan bagian yang tetap menarik walau ditonton tanpa konteks video penuh.
- Hindari klip yang isinya terlalu mirip satu sama lain.
- Jangan pilih klip yang terasa datar, bertele-tele, atau tidak punya payoff yang jelas.

ATURAN RETENTION & STRUKTUR KLIP:
- Pastikan 3 detik pertama klip punya daya tarik kuat: hook, konflik, rasa penasaran, statement tajam, emosi, atau pertanyaan implisit.
- Struktur ideal: hook -> context singkat -> tension/insight -> payoff.
- Jika bagian awal segmen terlalu lambat, geser start_time ke kalimat yang lebih kuat.
- Jika payoff sudah selesai, jangan memperpanjang klip tanpa alasan.
- Jangan memasukkan intro, basa-basi, jeda panjang, atau transisi yang tidak menambah daya tarik.
- Utamakan klip yang membuat penonton berhenti scroll, menonton sampai akhir, komentar, share, dan save.

ATURAN PEMOTONGAN TIMING:
- start_time sedekat mungkin dengan momen kuat pertama, bukan sekadar awal topik.
- end_time berhenti setelah payoff, kesimpulan, punchline, atau emotional beat utama selesai.
- Jangan potong terlalu awal jika kalimat masih menggantung.
- Klip harus tetap bisa dipahami tanpa menonton bagian sebelum atau sesudahnya.
- Dua momen kuat yang berdekatan boleh digabung selama durasi tetap {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} detik.
- Jika angle-nya berbeda, pisahkan sebagai kandidat klip berbeda.

PENILAIAN INTERNAL VIRAL_SCORE (JANGAN menambahkan field baru ke JSON):
- Hook strength: 1-20
- Emotional intensity: 1-20
- Shareability/comment potential: 1-20
- Standalone clarity: 1-20
- Payoff/retention: 1-20
- Jangan pilih klip dengan viral_score di bawah 70 kecuali jumlah momen bagus sangat terbatas.

KLASIFIKASI AKUN TUJUAN (UNTUK SETIAP KLIP):
Tentukan akun tujuan berdasarkan ANGLE video dari klip tersebut, bukan hanya topik:
{_build_account_classification_prompt()}

ATURAN KHUSUS KLASIFIKASI:
1. Beauty tidak otomatis masuk Life. (Omzet/brand -> Business. Review/lifestyle -> Life. Affiliate/konten -> Creator.)
2. Finance tidak otomatis masuk Business. (Omzet/bisnis -> Business. Personal finance/nabung -> Life. Cara bikin konten finance -> Creator.)
3. Owner story dibagi berdasarkan angle. (Perjuangan brand -> Business. Kehidupan pribadi/keluarga -> Life. Rezeki/ibadah -> Muslim.)

HOOK (WAJIB):
- Ambil 1 kalimat paling punchy yang ADA DI DALAM klip.
- Hook harus kuat dalam ~{durasi_hook} detik pertama dan benar-benar diucapkan dalam transkrip.
- Simpan sebagai hook_start_time dan hook_end_time.
- Jika hook terbaik tidak di awal kandidat, sesuaikan start_time agar hook muncul sedini mungkin.

TYPOGRAPHY PLAN (KINETIC TYPOGRAPHY):
- Pilih 3-6 kata TUNGGAL paling berbobot dari setiap klip.
- Untuk setiap kata: "kata_utama" (ejaan sama persis dengan transkrip), "scale_level" (1 normal, 2 besar, 3 raksasa), "style" ("utama"/"khusus"), "animasi" ("bounce_pop"/"stagger_up").
- Jangan pilih frasa panjang.

B-ROLL (WAJIB JIKA RELEVAN):
- Maksimal 1-3 momen per klip, masing-masing 3-7 detik: start_time, end_time, search_query (Bahasa Inggris, singkat).
- Jangan taruh B-roll tepat di detik yang sama dengan hook. Jika tidak ada yang cocok, isi [].

VISUAL B-ROLL HOOK (0-3 DETIK PERTAMA):
- Berikan 2-5 ide B-Roll pembuka yang kontras, lucu, dramatis, atau memancing rasa penasaran.
- Sertakan keyword pencarian dan alasan singkat mengapa ide itu bekerja.

BGM MOOD:
- Pilih SATU mood dari daftar baku: [chill, epic, sad, upbeat, suspense].

SLOW CLOSING:
- end_time HARUS ditambah padding +0.10 sampai +0.85 detik setelah kata terakhir.

ALASAN PEMILIHAN:
- Jelaskan nilai emosi, kekuatan hook, potensi retention, shareability, payoff, dan trigger viral utama.

ATURAN BAHASA METADATA:
- title_indonesia wajib, Bahasa Indonesia natural, maksimal 100 karakter (kompatibilitas internal).
- title_inggris, hastag, description_hook, description_context, keyword_tags, tiktok_caption wajib Bahasa Inggris natural.
- tiktok_title_id dan tiktok_caption_id wajib Bahasa Indonesia natural.
- Jangan mencampur bahasa di dalam satu field.

METADATA LINTAS PLATFORM:
1. title_indonesia: singkat, relevan, maksimal 100 karakter.
2. title_inggris: kuat, tajam, maksimal 100 karakter, fokus 1 ide utama.
3. hastag: 2-3 hashtag Bahasa Inggris dalam satu string, dipisah spasi.
4. description_hook: tepat 1 kalimat Bahasa Inggris yang memancing rasa ingin tahu.
5. description_context: tepat 1 kalimat Bahasa Inggris tentang konteks klip.
6. keyword_tags: 5-8 keyword pendek Bahasa Inggris (bukan hashtag).
7. tiktok_title_id: Bahasa Indonesia, lebih menjelaskan isi klip.
8. tiktok_caption_id: 1-2 kalimat Bahasa Indonesia natural.
9. tiktok_caption: 1-2 kalimat Bahasa Inggris natural, maksimal ~140 karakter.

ATURAN KUALITAS METADATA:
- Semua metadata sesuai isi klip, bukan isi video panjang.
- Jangan membuat janji yang tidak dibahas di klip; hindari hiperbola palsu.
- Prioritaskan angka, frasa kuat, atau statement tajam dari ucapan asli.
- Title, description, dan caption saling melengkapi.

ATURAN OUTPUT:
- Output HARUS berupa JSON array valid. Tanpa penjelasan di luar JSON.
- Semua field wajib terisi.
{segment_prompt}{hook_v2_prompt}

STRUKTUR JSON WAJIB (Ikuti nama field ini secara kaku):
[
  {{
    "rank": 1,
    "viral_score": 95,
    "start_time": 30.5,
    "end_time": 90.0,
    "hook_start_time": 30.5,
    "hook_end_time": 35.0,
    "bgm_mood": "chill",
    "typography_plan": [{{ "kata_utama": "...", "scale_level": 2, "style": "utama", "animasi": "bounce_pop" }}],
    "broll_list": [{{ "start_time": 40.0, "end_time": 45.0, "search_query": "..." }}],
    "recommended_visual_broll_hook": [
      {{ "broll_idea": "...", "search_keyword": "...", "why_it_works": "..." }}
    ],
    "hook_v2": {{
      "enabled": true,
      "items": [{{ "start_time": 31.0, "end_time": 32.5, "text": "KATA KUNCI" }}],
      "transition": {{ "type": "white_flash" }}
    }},
    "keep_segments": [
      {{ "start_time": 30.5, "end_time": 55.0 }},
      {{ "start_time": 58.0, "end_time": 90.0 }}
    ],
    "title_indonesia": "...",
    "title_inggris": "...",
    "hastag": "#hashtag1 #hashtag2",
    "description_hook": "...",
    "description_context": "...",
    "keyword_tags": ["tag1", "tag2"],
    "tiktok_title_id": "...",
    "tiktok_caption_id": "...",
    "tiktok_caption": "...",
    "alasan": "...",
    "klasifikasi_akun": {{
      "tipe_akun": "Creator",
      "akun_tujuan": "Creator.Mereska",
      "confidence": 87,
      "angle_utama": "...",
      "alasan": "...",
      "kata_kunci_pendukung": ["affiliate", "monetisasi"],
      "bio_akun": "...",
      "alternatif_akun": {{
        "tipe_akun": "Life",
        "akun_tujuan": "Life.Mereska",
        "alasan": "..."
      }}
    }}
  }}
]

Transkrip:
{transkrip_lengkap}
"""

"""
Local AI Service – Rule-based engine + Knowledge Base
Dùng khi không có API key hoặc làm lớp cache trước khi gọi API
"""
import re

# ──────────────────────────────────────────────
# GRAMMAR & FAQ KNOWLEDGE BASE
# ──────────────────────────────────────────────
GRAMMAR_KB = {
    # Thì động từ
    "hiện tại đơn": {
        "title": "Thì Hiện Tại Đơn (Simple Present)",
        "structure": "S + V(s/es) / S + am/is/are + ...",
        "usage": [
            "Diễn tả thói quen, hành động lặp đi lặp lại",
            "Sự thật hiển nhiên, quy luật tự nhiên",
            "Lịch trình cố định trong tương lai",
        ],
        "signal_words": ["always, usually, often, sometimes, never, every day/week/month"],
        "examples": [
            "She goes to school every day. (Cô ấy đi học mỗi ngày.)",
            "The sun rises in the east. (Mặt trời mọc ở phía đông.)",
            "Water boils at 100°C. (Nước sôi ở 100°C.)",
        ],
        "note": "Thêm -s/-es sau động từ khi chủ ngữ là he/she/it",
    },
    "hiện tại tiếp diễn": {
        "title": "Thì Hiện Tại Tiếp Diễn (Present Continuous)",
        "structure": "S + am/is/are + V-ing",
        "usage": [
            "Hành động đang xảy ra tại thời điểm nói",
            "Kế hoạch đã sắp xếp trong tương lai gần",
            "Xu hướng đang thay đổi",
        ],
        "signal_words": ["now, right now, at the moment, currently, at present"],
        "examples": [
            "She is studying English now. (Cô ấy đang học tiếng Anh.)",
            "I am meeting him tomorrow. (Tôi sẽ gặp anh ấy vào ngày mai.)",
            "Prices are rising. (Giá cả đang tăng.)",
        ],
        "note": "Không dùng với stative verbs: know, love, hate, want, need...",
    },
    "quá khứ đơn": {
        "title": "Thì Quá Khứ Đơn (Simple Past)",
        "structure": "S + V2/V-ed",
        "usage": [
            "Hành động đã hoàn thành trong quá khứ",
            "Chuỗi hành động xảy ra liên tiếp trong quá khứ",
        ],
        "signal_words": ["yesterday, ago, last night/week/year, in 2020, when..."],
        "examples": [
            "She visited Ha Noi last year. (Cô ấy đến Hà Nội năm ngoái.)",
            "I woke up, ate breakfast, and went to school. (Tôi thức dậy, ăn sáng rồi đi học.)",
        ],
        "note": "Động từ bất quy tắc: go→went, eat→ate, see→saw, have→had",
    },
    "hiện tại hoàn thành": {
        "title": "Thì Hiện Tại Hoàn Thành (Present Perfect)",
        "structure": "S + have/has + V3/V-ed",
        "usage": [
            "Hành động xảy ra trong quá khứ, kết quả còn ảnh hưởng đến hiện tại",
            "Kinh nghiệm sống (chưa xác định thời điểm cụ thể)",
            "Hành động mới vừa xảy ra",
        ],
        "signal_words": ["just, already, yet, ever, never, recently, since, for"],
        "examples": [
            "I have just finished my homework. (Tôi vừa làm xong bài tập.)",
            "She has never been to Paris. (Cô ấy chưa bao giờ đến Paris.)",
            "We have lived here for 5 years. (Chúng tôi đã sống ở đây 5 năm.)",
        ],
        "note": "Dùng 'since' với mốc thời gian, 'for' với khoảng thời gian",
    },
    "tương lai đơn": {
        "title": "Thì Tương Lai Đơn (Simple Future)",
        "structure": "S + will + V / S + am/is/are + going to + V",
        "usage": [
            "will: quyết định tức thì, lời hứa, dự đoán không chắc",
            "going to: kế hoạch đã có sẵn, dự đoán có bằng chứng",
        ],
        "signal_words": ["tomorrow, next week/month/year, in the future, soon"],
        "examples": [
            "I will help you. (Tôi sẽ giúp bạn.) — quyết định tức thì",
            "She is going to travel to Japan next month. (Cô ấy sẽ đi Nhật tháng sau.) — đã có kế hoạch",
        ],
        "note": "Không dùng will sau: when, if, before, after, until trong mệnh đề thời gian",
    },
    # Câu điều kiện
    "câu điều kiện": {
        "title": "Câu Điều Kiện (Conditional Sentences)",
        "structure": "3 loại chính",
        "usage": ["Diễn tả điều kiện và kết quả"],
        "examples": [
            "Loại 1 (có thể xảy ra): If + S + V(htđ), S + will + V\n   → If it rains, I will stay home.",
            "Loại 2 (không có thật hiện tại): If + S + V2/were, S + would + V\n   → If I were rich, I would travel the world.",
            "Loại 3 (không có thật quá khứ): If + S + had + V3, S + would have + V3\n   → If she had studied, she would have passed.",
        ],
        "note": "Loại 2: dùng 'were' cho tất cả chủ ngữ (If I were you...)",
    },
    "câu bị động": {
        "title": "Câu Bị Động (Passive Voice)",
        "structure": "S + be + V3/V-ed (+ by + O)",
        "usage": [
            "Khi hành động quan trọng hơn chủ thể",
            "Khi không biết hoặc không cần đề cập chủ thể",
        ],
        "examples": [
            "Active: The teacher explains the lesson. → Passive: The lesson is explained by the teacher.",
            "Active: Someone built this house in 1990. → Passive: This house was built in 1990.",
        ],
        "note": "Dạng be thay đổi theo thì: is/are, was/were, will be, has been...",
    },
    "mệnh đề quan hệ": {
        "title": "Mệnh Đề Quan Hệ (Relative Clauses)",
        "structure": "who, whom, whose, which, that",
        "usage": ["Bổ sung thông tin cho danh từ đứng trước"],
        "examples": [
            "who/that: cho người → The girl who/that lives next door is kind.",
            "which/that: cho vật → The book which/that I bought is interesting.",
            "whose: sở hữu → The boy whose dog bit me is my neighbor.",
            "whom: tân ngữ người → The teacher whom I respect is retiring.",
        ],
        "note": "Mệnh đề xác định (không dùng dấu phẩy) vs. Mệnh đề không xác định (dùng dấu phẩy)",
    },
}

# FAQ hỏi đáp học tiếng Anh
FAQ_KB = {
    "học tiếng anh": "**Cách học tiếng Anh hiệu quả:**\n\n1. 🎯 **Luyện nghe mỗi ngày** – Xem phim/video tiếng Anh với phụ đề\n2. 📖 **Đọc 15-20 phút/ngày** – Báo, sách dành cho trình độ bạn\n3. 🗣️ **Nói to khi học** – Luyện phát âm cùng từ mới\n4. ✍️ **Viết nhật ký** – 3-5 câu tiếng Anh mỗi ngày\n5. 🔄 **Ôn tập từ vựng** – Dùng flashcard, lặp lại ngắt quãng (spaced repetition)\n6. 🎵 **Học qua nhạc** – Nghe và hiểu lời bài hát tiếng Anh\n\n💡 **Mẹo:** Học 30 phút đều đặn mỗi ngày hiệu quả hơn học 3 tiếng cuối tuần!",

    "phát âm": "**Cách cải thiện phát âm tiếng Anh:**\n\n1. **Học IPA** – Bảng phiên âm quốc tế giúp đọc đúng bất kỳ từ nào\n2. **Shadowing** – Nghe và nhái lại y hệt người bản ngữ\n3. **Luyện âm khó:** \n   - /θ/ (th): lưỡi giữa răng → *think, three, through*\n   - /æ/ (a ngắn): *cat, bad, man*\n   - /ɪ/ vs /iː/: *bit* vs *beat*\n4. **Ghi âm bản thân** và so sánh\n5. **Dùng Google Translate** để nghe phát âm chuẩn\n\n🔊 **Thực hành:** Đọc 10 từ mới to mỗi ngày!",

    "từ vựng": "**Chiến lược học từ vựng:**\n\n1. 📱 **Anki/Flashcard** – Spaced repetition system rất hiệu quả\n2. 🌳 **Word families** – Học cả nhóm: *act → action → active → activity*\n3. 📝 **Ngữ cảnh** – Học từ trong câu, không học riêng lẻ\n4. 🖼️ **Hình ảnh hóa** – Liên kết từ với hình ảnh sinh động\n5. ✍️ **Dùng ngay** – Đặt câu với từ mới vừa học\n6. 🔁 **Ôn tập:** Ngày 1 → Ngày 3 → Tuần 1 → Tháng 1\n\n🎯 **Mục tiêu:** 10 từ mới mỗi ngày = 3,650 từ/năm!",

    "ngữ pháp": "**Học ngữ pháp tiếng Anh hiệu quả:**\n\n1. **Hiểu cấu trúc** – Đừng học thuộc lòng, hãy hiểu *vì sao*\n2. **Thực hành ngay** – Đặt 3 câu với mỗi cấu trúc mới\n3. **Đọc nhiều** – Ngữ pháp sẽ tự nhiên khi bạn tiếp xúc đủ nhiều\n4. **Tập trung vào thì** – Nắm vững 8 thì cơ bản trước\n\n📚 **Ưu tiên học:**\n- Thì hiện tại, quá khứ, tương lai\n- Câu điều kiện\n- Câu bị động\n- Mệnh đề quan hệ",

    "ielts": "**Lộ trình học IELTS:**\n\n📊 **Thang điểm:** 0-9, đại học thường yêu cầu 6.0-7.0\n\n**4 kỹ năng cần luyện:**\n- 📖 **Reading:** Đọc nhiều, luyện skimming/scanning\n- 👂 **Listening:** Nghe BBC, VOA; làm bài thi thử\n- ✍️ **Writing:** Task 1 (biểu đồ) + Task 2 (luận văn)\n- 🗣️ **Speaking:** Luyện 3 phần, ghi âm bản thân\n\n⏱️ **Thời gian chuẩn bị:**\n- 5.0 → 6.0: ~3-6 tháng\n- 6.0 → 7.0: ~6-12 tháng\n\n💡 **Tài liệu:** Cambridge IELTS, British Council, IDP Vietnam",

    "toeic": "**Luyện thi TOEIC:**\n\n📊 **Thang điểm:** 10-990 (L&R)\n\n**Cấu trúc đề thi:**\n- 👂 **Listening (495đ):** Part 1-4 (photos, Q&A, conversations, talks)\n- 📖 **Reading (495đ):** Part 5-7 (grammar, reading comprehension)\n\n🎯 **Chiến lược:**\n- Part 5: Làm nhanh trong 20-25 giây/câu\n- Part 7: Đọc câu hỏi trước, sau đó đọc bài\n- Nghe: Tập trung từ khóa, đừng cố hiểu 100%\n\n📚 **Tài liệu:** ETS Official Guide, Economy TOEIC",

    "phân biệt": "Bạn muốn phân biệt từ/cấu trúc nào? Hãy gõ rõ hơn, ví dụ:\n- 'phân biệt make và do'\n- 'phân biệt in/on/at'\n- 'phân biệt some và any'",

    "make do": "**Phân biệt MAKE vs DO:**\n\n🔨 **MAKE** – tạo ra, sản xuất:\n- make a mistake (phạm sai lầm)\n- make a decision (đưa ra quyết định)\n- make friends (kết bạn)\n- make money (kiếm tiền)\n- make a phone call\n\n✅ **DO** – thực hiện, làm việc:\n- do homework (làm bài tập)\n- do the dishes (rửa bát)\n- do exercise (tập thể dục)\n- do business (kinh doanh)\n- do your best (cố gắng hết mình)\n\n💡 **Quy tắc nhớ:** MAKE = tạo ra sản phẩm/kết quả; DO = hoạt động không có sản phẩm cụ thể",

    "say tell speak talk": "**Phân biệt SAY / TELL / SPEAK / TALK:**\n\n💬 **SAY** – nói gì (tập trung vào nội dung):\n- She said 'hello'. / She said (that) she was tired.\n- ❌ say someone (không dùng tân ngữ người)\n\n📢 **TELL** – nói với ai (luôn có tân ngữ người):\n- Tell me the truth. / He told her a story.\n- tell a lie, tell the time, tell the difference\n\n🗣️ **SPEAK** – nói (trang trọng hơn, tập trung khả năng):\n- She speaks English fluently.\n- speak to/with someone, speak at a conference\n\n💭 **TALK** – nói chuyện (qua lại, không trang trọng):\n- We talked for hours.\n- talk to/with someone, talk about something",

    "giới từ": "**Giới từ thời gian IN / ON / AT:**\n\n📅 **IN** – khoảng thời gian rộng:\n- in + tháng: in January\n- in + năm: in 2024\n- in + mùa: in summer\n- in + buổi: in the morning/afternoon/evening\n\n📆 **ON** – ngày cụ thể:\n- on + thứ: on Monday\n- on + ngày: on July 4th\n- on + dịp: on Christmas Day, on my birthday\n\n⏰ **AT** – thời điểm chính xác:\n- at + giờ: at 8 o'clock\n- at night, at noon, at midnight\n- at the weekend (Br.Eng)",
}

# Phát hiện ngôn ngữ đơn giản
def _detect_language(text: str) -> str:
    """Phát hiện văn bản là tiếng Anh hay tiếng Việt."""
    vietnamese_chars = set("àáâãèéêìíòóôõùúýăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ")
    text_lower = text.lower()
    vi_count = sum(1 for c in text_lower if c in vietnamese_chars)
    return "vi" if vi_count > 0 else "en"


def _find_grammar_topic(question: str) -> dict | None:
    """Tìm chủ đề ngữ pháp từ câu hỏi."""
    q = question.lower()
    
    # Từ khóa mapping
    keyword_map = {
        "hiện tại đơn": ["hiện tại đơn", "simple present", "present simple", "thì htđ"],
        "hiện tại tiếp diễn": ["tiếp diễn", "continuous", "đang làm", "present continuous"],
        "quá khứ đơn": ["quá khứ đơn", "simple past", "past simple", "thì qkđ"],
        "hiện tại hoàn thành": ["hoàn thành", "perfect", "present perfect", "vừa mới", "đã từng"],
        "tương lai đơn": ["tương lai", "future", "will", "going to", "sẽ làm"],
        "câu điều kiện": ["điều kiện", "conditional", "if clause", "mệnh đề if"],
        "câu bị động": ["bị động", "passive", "passive voice"],
        "mệnh đề quan hệ": ["quan hệ", "relative", "who whom which whose that"],
    }
    
    for topic, keywords in keyword_map.items():
        if any(kw in q for kw in keywords):
            return GRAMMAR_KB.get(topic)
    return None


def _find_faq(question: str) -> str | None:
    """Tìm câu trả lời từ FAQ."""
    q = question.lower()
    
    faq_map = {
        "học tiếng anh": ["học tiếng anh", "cách học", "học english", "improve english", "bắt đầu học"],
        "phát âm": ["phát âm", "pronunciation", "đọc đúng", "accent"],
        "từ vựng": ["từ vựng", "vocabulary", "học từ mới", "new words", "word"],
        "ngữ pháp": ["ngữ pháp", "grammar", "cấu trúc ngữ pháp"],
        "ielts": ["ielts", "band", "điểm ielts"],
        "toeic": ["toeic", "listening reading"],
        "make do": ["make và do", "make vs do", "make or do", "phân biệt make"],
        "say tell speak talk": ["say tell", "speak talk", "say vs tell", "speak vs talk"],
        "giới từ": ["in on at", "giới từ thời gian", "preposition time"],
    }
    
    for key, keywords in faq_map.items():
        if any(kw in q for kw in keywords):
            return FAQ_KB.get(key)
    return None


def format_grammar_response(grammar: dict) -> str:
    """Định dạng câu trả lời ngữ pháp."""
    lines = [f"## {grammar['title']}\n"]
    
    if grammar.get("structure"):
        lines.append(f"**🔧 Cấu trúc:** `{grammar['structure']}`\n")
    
    if grammar.get("usage"):
        lines.append("**📌 Cách dùng:**")
        for u in grammar["usage"]:
            lines.append(f"- {u}")
        lines.append("")
    
    if grammar.get("signal_words"):
        lines.append(f"**🔍 Dấu hiệu nhận biết:** {', '.join(grammar['signal_words'])}\n")
    
    if grammar.get("examples"):
        lines.append("**💡 Ví dụ:**")
        for ex in grammar["examples"]:
            lines.append(f"- {ex}")
        lines.append("")
    
    if grammar.get("note"):
        lines.append(f"**⚠️ Lưu ý:** {grammar['note']}")
    
    return "\n".join(lines)


# ──────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────

def ask_question_local(question: str) -> dict:
    """Trả lời câu hỏi từ knowledge base local."""
    # 1. Thử tìm chủ đề ngữ pháp
    grammar = _find_grammar_topic(question)
    if grammar:
        return {
            "answer": format_grammar_response(grammar),
            "source": "local_kb",
        }
    
    # 2. Thử tìm FAQ
    faq = _find_faq(question)
    if faq:
        return {"answer": faq, "source": "local_kb"}
    
    # 3. Gợi ý dựa theo từ khóa detect
    q_lower = question.lower()
    
    if any(w in q_lower for w in ["ví dụ", "example", "câu ví dụ", "đặt câu"]):
        return {
            "answer": "Vui lòng dùng tab **'Tạo ví dụ'** và nhập từ cần đặt câu để tôi tạo ví dụ cho bạn! ✨",
            "source": "local_kb",
        }
    
    if any(w in q_lower for w in ["nghĩa", "nghĩa của", "có nghĩa", "mean", "meaning", "là gì"]):
        return {
            "answer": "Vui lòng dùng tab **'Giải thích từ vựng'** và nhập từ tiếng Anh để tôi giải thích chi tiết! 📖",
            "source": "local_kb",
        }
    
    if any(w in q_lower for w in ["dịch", "translate", "translation"]):
        return {
            "answer": "Vui lòng dùng tab **'Dịch thuật'** để tôi dịch nội dung cho bạn! 🌐",
            "source": "local_kb",
        }
    
    return None  # Không tìm thấy trong local KB


def explain_vocabulary_local(word: str, vocab_doc: dict = None) -> dict:
    """Giải thích từ vựng từ DB hoặc local."""
    if vocab_doc:
        lines = [
            f"## 📖 {vocab_doc.get('word', word).upper()}",
            "",
            f"**Phiên âm:** `{vocab_doc.get('ipa', '')}`" if vocab_doc.get('ipa') else "",
            f"**Nghĩa:** {vocab_doc.get('meaning_vi', '')}",
            "",
        ]
        if vocab_doc.get("example_sentence"):
            lines += [
                "**Ví dụ:**",
                f"- *{vocab_doc['example_sentence']}*",
                f"  → {vocab_doc.get('example_translation', '')}",
            ]
        if vocab_doc.get("category"):
            lines.append(f"\n**Chủ đề:** {vocab_doc['category']}")
        if vocab_doc.get("difficulty"):
            lines.append(f"**Độ khó:** {vocab_doc['difficulty']}")
        
        return {
            "explanation": "\n".join(l for l in lines if l is not None),
            "source": "database",
        }
    
    return None  # Không có trong DB, cần gọi API


def generate_examples_local(word: str, vocab_doc: dict = None) -> dict:
    """Tạo câu ví dụ từ template."""
    
    # Nếu có trong DB, ưu tiên ví dụ từ DB
    if vocab_doc and vocab_doc.get("example_sentence"):
        result = (
            f"**Câu ví dụ cho từ '{word}':**\n\n"
            f"1. *{vocab_doc['example_sentence']}*\n"
            f"   → {vocab_doc.get('example_translation', '')}\n"
        )
        return {"answer": result, "source": "database"}
    
    return None  # Cần API để tạo thêm ví dụ


def translate_local(text: str, vocab_doc: dict = None) -> dict:
    """Dịch đơn giản từ DB nếu là từ đơn."""
    if vocab_doc:
        return {
            "translation": (
                f"**{vocab_doc.get('word', text)}** → {vocab_doc.get('meaning_vi', '')}\n\n"
                f"📖 Phiên âm: `{vocab_doc.get('ipa', '')}`"
                if vocab_doc.get('ipa') else
                f"**{vocab_doc.get('word', text)}** → {vocab_doc.get('meaning_vi', '')}"
            ),
            "source": "database",
        }
    return None

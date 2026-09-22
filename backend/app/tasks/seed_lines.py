"""What the seeded customers say, and what the bots said back (tasks 39.1, 39.2, 39.4).

Two kinds. The ordinary conversations (`TOPICS`): a price asked, an opening
hour, a known issue looked up. And the ones that end in a document (`DEALS`): a
food order, a hotel booking, a support ticket, a property viewing. Those are
templates rather than finished lines, because the number in the reply -- FD-,
BK-, TCK-, viewing # -- only exists once the seed has filed the document in the
back office it belongs to, and the reply has to name the one that is there.

Every figure in a reply is the one in the bot's own `app/bots/data/*.json`. A
seeded reply quoting a price the live bot would not quote is the one thing on
this screen a customer could catch. Where a topic names a tool, the tool's
output is not written here at all: the seed calls the real tool for it, so the
card on the console is what that tool answers today.

Tool inputs stay in English whatever the conversation's language, as the model
writes them: `saas_search_known_issues` matches English words and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass, field

LANGUAGES = ("zh", "en", "ms")


@dataclass(frozen=True)
class Topic:
    ask: str
    reply: str
    tool: str = ""
    tool_input: dict = field(default_factory=dict)


# Thirty each: five industries times six ordinary customers, in each language.
NAMES: dict[str, tuple[str, ...]] = {
    "zh": (
        "林伟杰", "黄慧敏", "陈志豪", "李淑婷", "张国强", "王美玲", "吴俊贤", "刘佩珊", "郑家豪", "蔡雅琪",
        "许文龙", "杨欣怡", "何振宇", "谢丽华", "梁子健", "罗晓彤", "邱明辉", "叶素芬", "曾浩然", "潘嘉欣",
        "Jason Tan", "Michelle Lim", "Kelvin Ong", "Vivian Chong", "Alvin Goh", "Eunice Teh", "Ryan Chew",
        "Jolene Yap", "Desmond Lau", "Crystal Khoo",
    ),
    "en": (
        "Priya Nair", "Daniel Wong", "Sarah Lee", "Arjun Menon", "Rachel Ng", "Marcus Tan", "Emily Chua",
        "Kavitha Raj", "Jonathan Yeo", "Natalie Soo", "Vikram Pillai", "Grace Loh", "Benjamin Koh",
        "Deepa Krishnan", "Aaron Lim", "Sophia Cheah", "Ravi Subramaniam", "Hannah Low", "Nicholas Ho",
        "Janice Foo", "Suresh Kumar", "Olivia Tay", "Adrian Seah", "Meera Das", "Ethan Liew", "Chloe Wee",
        "Ganesh Rao", "Amanda Kok", "Justin Leong", "Samantha Gan",
    ),
    "ms": (
        "Nurul Aina", "Ahmad Firdaus", "Siti Hajar", "Muhammad Hafiz", "Nur Syafiqah", "Mohd Azlan",
        "Aisyah Rahman", "Faizal Hamid", "Farah Nadia", "Hakim Zulkifli", "Nor Azizah", "Amirul Hakim",
        "Zulaikha Ismail", "Khairul Anuar", "Liyana Yusof", "Syafiq Rosli", "Hidayah Omar", "Irfan Kamal",
        "Balqis Harun", "Danial Aziz", "Izzati Salleh", "Haziq Rahim", "Sofea Idris", "Aiman Shah",
        "Najwa Latif", "Rizal Mansor", "Atiqah Jamal", "Luqman Hakimi", "Wardah Said", "Arif Ramli",
    ),
}

THANKS: dict[str, tuple[Topic, ...]] = {
    "zh": (
        Topic("好的，谢谢！", "不客气😊 还有什么需要随时找我。"),
        Topic("明白了 thanks", "没问题！祝您有美好的一天。"),
        Topic("ok noted", "好的，有问题随时 WhatsApp 我们。"),
    ),
    "en": (
        Topic("Great, thanks!", "You're welcome 😊 Just message here anytime if you need anything else."),
        Topic("ok noted, thank you", "No problem! Have a great day."),
        Topic("Cool, that helps", "Glad to help! Let me know if anything else comes up."),
    ),
    "ms": (
        Topic("Ok terima kasih!", "Sama-sama 😊 Mesej je kalau ada apa-apa lagi."),
        Topic("Baik, faham", "Terima kasih! Semoga hari anda baik."),
        Topic("Ok noted, tq", "Sama-sama! Kami sedia membantu bila-bila masa."),
    ),
}

TOPICS: dict[str, dict[str, tuple[Topic, ...]]] = {
    "retail": {
        "zh": (
            Topic(
                "请问可以 COD 吗？",
                "可以的，*Klang Valley 范围内、订单 RM 500 以下*支持货到付款（COD）。超过 RM 500 或在外坡的话，需要先在线付款哦。",
            ),
            Topic(
                "寄到槟城要几天？",
                "西马境内标准配送是 *2-4 个工作日*，槟城也在这个范围。沙巴和砂拉越是 4-7 个工作日。",
            ),
            Topic(
                "东西买了不合适可以退吗",
                "可以的，收货后 *7 天内*、商品没用过并保留原包装就能退。退款会在 5-7 个工作日内处理完成。",
            ),
            Topic(
                "你们客服几点下班？",
                "我们的人工客服时间是 *周一到周六 9am-6pm*（马来西亚时间）。其他时间可以直接留言，我先帮您处理。",
            ),
        ),
        "en": (
            Topic(
                "Hi, do you do cash on delivery?",
                "Yes! Cash on delivery is available for orders *under RM 500 within Klang Valley*. For larger orders or other areas, online payment is needed.",
            ),
            Topic(
                "How long does shipping to Kuching take?",
                "Deliveries to Sabah and Sarawak take *4-7 business days*. Within Peninsular Malaysia it's 2-4 business days.",
            ),
            Topic(
                "What's your return policy?",
                "Items can be returned within *7 days of delivery* if unused and in the original packaging. Refunds are processed within 5-7 business days.",
            ),
            Topic(
                "We're a company, can we get invoice with payment terms?",
                "Yes, trade accounts are invoiced with *30-day payment terms*, and all prices include SST where it applies. I can open a trade account for you whenever you're ready to order.",
            ),
        ),
        "ms": (
            Topic(
                "Boleh bayar COD tak?",
                "Boleh! COD tersedia untuk pesanan *bawah RM 500 di Lembah Klang*. Untuk pesanan lebih besar atau kawasan lain, perlu bayar secara online.",
            ),
            Topic(
                "Berapa lama nak sampai JB?",
                "Penghantaran standard di Semenanjung Malaysia ambil masa *2-4 hari bekerja*, termasuk Johor Bahru.",
            ),
            Topic(
                "Kalau barang tak sesuai boleh pulang?",
                "Boleh, dalam masa *7 hari selepas terima* asalkan belum digunakan dan dalam pembungkusan asal. Bayaran balik diproses dalam 5-7 hari bekerja.",
            ),
            Topic(
                "Customer service buka pukul berapa?",
                "Khidmat pelanggan kami buka *Isnin hingga Sabtu, 9am-6pm* waktu Malaysia. Di luar waktu itu, tinggalkan mesej dan saya bantu dulu.",
            ),
        ),
    },
    "food": {
        "zh": (
            Topic(
                "你们送到哪里？",
                "我们从吉隆坡分店出发，*8 公里范围内*都可以送，运费统一 *RM 5*。",
            ),
            Topic(
                "nasi lemak 多少钱",
                "*Nasi Lemak Special* 是 *RM 12.90*，有椰浆饭、参巴、炸鸡、蛋、江鱼仔和花生。要帮您加进购物车吗？",
            ),
            Topic(
                "一般多久送到？",
                "大部分订单下单后 *15 分钟左右*就到：厨房准备几分钟，骑手路上大约 10 分钟。",
            ),
            Topic(
                "公司活动要订 50 人份可以吗",
                "可以的！RM 300 以上的活动订单，麻烦*至少提前 24 小时*通知我们，方便厨房备料。",
            ),
        ),
        "en": (
            Topic(
                "Do you deliver to Bangsar?",
                "We deliver within an *8km radius* of our Kuala Lumpur outlet for a flat *RM 5* delivery fee, so Bangsar is covered 👍",
            ),
            Topic(
                "What drinks do you have?",
                "We have *Teh Tarik* (RM 4.50) and *Iced Milo* (RM 5.00). For dessert there's *Cendol* at RM 7.00.",
            ),
            Topic(
                "Anything with prawns?",
                "Yes! *Butter Prawns* (RM 22.00), *Char Kway Teow* with prawns and cockles (RM 13.50), and *Mee Goreng Mamak* (RM 10.90).",
            ),
            Topic(
                "Can you cater for an office party?",
                "Yes! For orders above RM 300, please give us *at least 24 hours notice* so the kitchen can prepare.",
            ),
        ),
        "ms": (
            Topic(
                "Hantar sampai Cheras tak?",
                "Kami hantar dalam lingkungan *8km* dari cawangan Kuala Lumpur, caj penghantaran tetap *RM 5*.",
            ),
            Topic(
                "Roti canai berapa?",
                "*Roti Canai (2 keping)* RM 6.00, dihidang dengan kuah dhal. Nak saya masukkan dalam troli?",
            ),
            Topic(
                "Lama tak nak sampai?",
                "Kebanyakan pesanan sampai dalam *15 minit*: dapur perlukan beberapa minit dan perjalanan lebih kurang 10 minit.",
            ),
            Topic(
                "Satay ada?",
                "Ada! *Satay Chicken (10 cucuk)* RM 15.00 dengan kuah kacang.",
            ),
        ),
    },
    "realestate": {
        "zh": (
            Topic(
                "首付一般要多少？",
                "一般是房价的 *10%*，不过具体要看银行和批下来的贷款成数。",
            ),
            Topic(
                "Mont Kiara 那间还在吗",
                "在的！*PROP-201* Mont Kiara 的 Condo，1,100 sqft、3 房，售价 *RM 850,000*，目前 Available。要帮您约看房吗？",
            ),
            Topic(
                "预算 50 万以内有什么",
                "RM 500,000 以内目前有两套在售：\n• *PROP-206* Cheras Condo，3 房 900 sqft，RM 450,000\n• *PROP-204* KLCC Studio，550 sqft，RM 480,000\nAmpang 那套 RM 380,000 的已经 Under offer 了。",
            ),
            Topic(
                "外国人可以买吗？",
                "可以的，外国人在大部分州一般可以购买 *RM 1,000,000 以上*的房产，具体以各州规定为准。",
            ),
        ),
        "en": (
            Topic(
                "Any landed property in PJ?",
                "Yes, *PROP-203* is a Terrace House in Petaling Jaya: 4 bedrooms, 1,800 sqft, *RM 980,000*. Would you like to arrange a viewing?",
            ),
            Topic(
                "What's the typical down payment?",
                "Typically *10%* of the property price, though this varies by bank and the loan margin approved.",
            ),
            Topic(
                "Is the Ampang apartment still available?",
                "*PROP-207* in Ampang is currently *under offer*, sorry. A similar option is *PROP-202* in Bangsar South: 2 bedrooms, 950 sqft, RM 620,000.",
            ),
            Topic(
                "Can foreigners buy in KL?",
                "Yes, foreigners can generally buy property *above RM 1,000,000* in most states, subject to state-specific rules.",
            ),
        ),
        "ms": (
            Topic(
                "Deposit rumah biasanya berapa?",
                "Biasanya *10%* daripada harga rumah, tetapi bergantung pada bank dan margin pinjaman yang diluluskan.",
            ),
            Topic(
                "Ada rumah besar untuk keluarga?",
                "Ada! *PROP-205* Semi-D di Subang Jaya, 5 bilik, 2,600 sqft, *RM 1,650,000*. Nak saya aturkan lawatan?",
            ),
            Topic(
                "Bawah RM 500k ada?",
                "Ada dua unit:\n• *PROP-206* Condo Cheras, 3 bilik, RM 450,000\n• *PROP-204* Studio KLCC, 550 sqft, RM 480,000",
            ),
            Topic(
                "Macam mana nak buat viewing?",
                "Beritahu je listing mana dan tarikh/masa yang sesuai, kami akan sahkan dengan ejen hartanah.",
            ),
        ),
    },
    "hotel": {
        "zh": (
            Topic(
                "兰卡威两个人住有什么房型？",
                "兰卡威适合 2 位入住的房型有：\n• *Standard Twin Room* RM 220/晚\n• *Deluxe Garden Room* RM 320/晚\n• *Family Suite* RM 480/晚\n• *Sea View Suite* RM 580/晚（含早餐）\n• *Beachfront Villa* RM 950/晚（私人泳池）",
                "hotel_search_rooms",
                {"location": "Langkawi", "guests": 2},
            ),
            Topic(
                "几点可以 check in？",
                "入住时间是 *下午 3 点起*，退房 *中午 12 点前*。提早入住或延迟退房视当天情况安排。",
            ),
            Topic(
                "有接机服务吗",
                "有的，兰卡威机场（LGK）和槟城机场（PEN）接送都是 *RM 80 单程*。",
            ),
            Topic(
                "槟城有什么房",
                "槟城目前有：\n• *Superior City Room* RM 260/晚\n• *Heritage Suite* RM 420/晚（含早餐）\n• *Penthouse* RM 890/晚（屋顶露台）",
                "hotel_search_rooms",
                {"location": "Penang"},
            ),
        ),
        "en": (
            Topic(
                "We're a family of 4, any rooms in Langkawi?",
                "For 4 guests in Langkawi:\n• *Family Suite* RM 480/night, two bedrooms + kids club\n• *Beachfront Villa* RM 950/night, private pool and direct beach access",
                "hotel_search_rooms",
                {"location": "Langkawi", "guests": 4},
            ),
            Topic(
                "Is breakfast included?",
                "Breakfast is included for the *Sea View Suite and above*. Other room types can add breakfast for *RM 45 per person per day*.",
            ),
            Topic(
                "Rooms in Penang for 2?",
                "In Penang for 2 guests:\n• *Superior City Room* RM 260/night\n• *Heritage Suite* RM 420/night, breakfast included\n• *Penthouse* RM 890/night, rooftop terrace",
                "hotel_search_rooms",
                {"location": "Penang", "guests": 2},
            ),
            Topic(
                "Do you have airport pickup?",
                "Yes, airport transfers from Langkawi (LGK) and Penang (PEN) airports are *RM 80 per way*.",
            ),
        ),
        "ms": (
            Topic(
                "Bilik di Langkawi bawah RM 300 ada?",
                "Ada, *Standard Twin Room* RM 220 semalam, katil kembar dan WiFi percuma.",
                "hotel_search_rooms",
                {"location": "Langkawi", "max_price_rm": 300},
            ),
            Topic(
                "Check-in pukul berapa?",
                "Check-in *dari 3:00 petang*, check-out *sebelum 12:00 tengah hari*. Check-in awal tertakluk pada kekosongan.",
            ),
            Topic(
                "Sarapan termasuk tak?",
                "Sarapan termasuk untuk *Sea View Suite ke atas*. Bilik lain boleh tambah sarapan *RM 45 seorang sehari*.",
            ),
            Topic(
                "Ada transport dari airport?",
                "Ada, pemindahan dari lapangan terbang Langkawi (LGK) dan Pulau Pinang (PEN) *RM 80 sehala*.",
            ),
        ),
    },
    "saas": {
        "zh": (
            Topic(
                "Slack 通知同步不了",
                "这个是已知问题：请到 *Settings > Integrations > Slack* 点 *Reconnect*。授权 token 每 90 天会过期，重新连接就会刷新。",
                "saas_search_known_issues",
                {"query": "Slack integration not syncing"},
            ),
            Topic(
                "上传文件一直卡在 0%",
                "一般是浏览器缓存的问题，可以先*清除缓存*或用*无痕窗口*再试。超过 500MB 的文件也可能超时，建议分开上传。",
                "saas_search_known_issues",
                {"query": "file upload stuck at 0%"},
            ),
            Topic(
                "Team 套餐多少钱？",
                "*Team* 是 *RM 49/月*，20 个席位，无限项目、集成和数据分析。需要 SSO 的话可以看 *Business*，RM 149/月、100 席位。",
            ),
            Topic(
                "dashboard 打开很慢",
                "任务超过 1000 条的工作区可能会这样。可以先*归档已完成的项目*，或者我们帮您开启 performance mode（beta）。",
                "saas_search_known_issues",
                {"query": "dashboard loading slowly"},
            ),
        ),
        "en": (
            Topic(
                "I can't log in, keeps saying invalid credentials",
                "Please try resetting your password via the *Forgot Password* link. If your company uses SSO, check with your workspace admin that your account is still active.",
                "saas_search_known_issues",
                {"query": "can't log in invalid credentials"},
            ),
            Topic(
                "Notifications stopped showing up",
                "Check *Settings > Notifications* to make sure they're enabled, and check your browser's notification permissions for our domain.",
                "saas_search_known_issues",
                {"query": "notifications not showing up"},
            ),
            Topic(
                "What's the difference between Team and Business?",
                "*Team* is RM 49/month for 20 seats with unlimited projects, integrations and analytics. *Business* is RM 149/month for 100 seats and adds SSO, advanced permissions and priority support.",
            ),
            Topic(
                "Slack integration not syncing since yesterday",
                "Go to *Settings > Integrations > Slack* and click *Reconnect*. That refreshes the auth token, which expires every 90 days.",
                "saas_search_known_issues",
                {"query": "Slack integration not syncing"},
            ),
        ),
        "ms": (
            Topic(
                "Tak boleh login, invalid credentials",
                "Cuba set semula kata laluan melalui pautan *Forgot Password*. Jika guna SSO, semak dengan admin workspace bahawa akaun anda masih aktif.",
                "saas_search_known_issues",
                {"query": "can't log in invalid credentials"},
            ),
            Topic(
                "Pakej percuma ada tak?",
                "Ada, pakej *Starter* percuma untuk 5 pengguna dan 2 projek. Untuk projek tanpa had, *Team* RM 49 sebulan.",
            ),
            Topic(
                "Notifikasi tak keluar",
                "Semak *Settings > Notifications* untuk pastikan ia dihidupkan, dan semak kebenaran notifikasi pelayar untuk domain kami.",
                "saas_search_known_issues",
                {"query": "notifications not showing up"},
            ),
            Topic(
                "Upload fail stuck 0%",
                "Biasanya masalah cache pelayar. Cuba *kosongkan cache* atau guna *tetingkap incognito*. Fail melebihi 500MB juga mungkin tamat masa, cuba pecahkan fail.",
                "saas_search_known_issues",
                {"query": "file upload stuck"},
            ),
        ),
    },
}


# --- conversations that end in a document (task 39.2) --------------------------

# Within the food outlet's 8km of central Kuala Lumpur.
ADDRESSES = (
    "No. 12, Jalan Telawi 3, Bangsar Baru, 59100 Kuala Lumpur",
    "B-12-3, Residensi Pantai, Jalan Pantai Dalam, 59200 Kuala Lumpur",
    "Unit 8-2, Menara KL Eco City, Jalan Bangsar, 59200 Kuala Lumpur",
    "15, Jalan Kampung Pandan, 55100 Kuala Lumpur",
    "7, Lorong Maarof, Bangsar Park, 59000 Kuala Lumpur",
    "A-3-5, Sri Putramas, Jalan Kuching, 51200 Kuala Lumpur",
    "21, Jalan Ampang Hilir, 55000 Kuala Lumpur",
    "Level 9, Wisma UOA II, Jalan Pinang, 50450 Kuala Lumpur",
)

# What a customer raises that the known-issues list does not cover, which is
# exactly when the bot opens a ticket. The query is what the model would search
# with; a test holds that none of them matches a known issue, or the bot on
# screen would be opening a ticket for something it should have fixed.
ISSUES = (
    {
        "query": "export pdf fails",
        "subject": "Export to PDF fails on a large project",
        "description": "Export to PDF fails every time on the main project (300+ items). Smaller projects export fine.",
        "priority": "normal",
        "ask": {
            "zh": "导出 PDF 一直失败，我们主项目有 300 多条，小项目就没问题",
            "en": "Export to PDF keeps failing on our main project, it has 300+ items. Small projects are fine",
            "ms": "Export PDF asyik gagal untuk projek utama kami (300+ item). Projek kecil ok je",
        },
    },
    {
        "query": "invitation email never arrived",
        "subject": "New teammate never receives the invitation email",
        "description": "Invited a new teammate twice; the invitation email never arrived, including the spam folder.",
        "priority": "normal",
        "ask": {
            "zh": "邀请新同事加入，发了两次邀请邮件他都没收到，垃圾箱也没有",
            "en": "I invited a new teammate twice but the invitation email never arrived, not in spam either",
            "ms": "Saya dah jemput rakan sekerja baru dua kali tapi email jemputan tak sampai, spam pun takde",
        },
    },
    {
        "query": "billing charged twice",
        "subject": "Charged twice for the Team plan this month",
        "description": "The card was charged twice for the Team plan (RM 49) this month.",
        "priority": "high",
        "ask": {
            "zh": "这个月 Team 套餐扣了我们两次钱，RM 49 扣了两笔",
            "en": "We got charged twice for the Team plan this month, two RM 49 charges on the card",
            "ms": "Bulan ni kami kena caj dua kali untuk pakej Team, dua kali RM 49",
        },
    },
    {
        "query": "recurring item stopped generating",
        "subject": "Recurring items stopped being generated",
        "description": "Weekly recurring items stopped being generated since Monday; the whole team relies on them.",
        "priority": "urgent",
        "ask": {
            "zh": "每周自动重复的事项从星期一开始就没有生成了，整个团队都靠这个",
            "en": "Our weekly recurring items stopped generating since Monday, the whole team depends on them",
            "ms": "Item berulang mingguan tak dijana sejak Isnin, satu team bergantung pada benda ni",
        },
    },
)

PRIORITY_WORDS = {
    "zh": {"low": "低", "normal": "普通", "high": "高", "urgent": "紧急"},
    "en": {"low": "low", "normal": "normal", "high": "high", "urgent": "urgent"},
    "ms": {"low": "rendah", "normal": "biasa", "high": "tinggi", "urgent": "segera"},
}

VIEWING_TIMES = {
    "zh": ("早上10点", "下午3点", "晚上7点"),
    "en": ("10am", "3pm", "after 6pm"),
    "ms": ("10 pagi", "petang", "lepas kerja"),
}

LOCATION_WORDS = {
    "zh": {"Langkawi": "兰卡威", "Penang": "槟城"},
    "en": {"Langkawi": "Langkawi", "Penang": "Penang"},
    "ms": {"Langkawi": "Langkawi", "Penang": "Pulau Pinang"},
}

# Format strings, filled from the document as it was filed.
DEALS: dict[str, dict[str, dict[str, str]]] = {
    "food": {
        "zh": {
            "item": "{quantity}份 {name}",
            "joiner": "、",
            "ask_items": "我要{items}",
            "cart_line": "• {quantity} × {name}  {line_total}",
            "cart_reply": "好的，购物车里有：\n{lines}\n运费 {fee}，共 *{total}*。送到哪里呢？",
            "ask_address": "送到 {address}",
            "placed_reply": "下单成功 ✅ 订单号 *{order_no}*，共 *{total}*。大约 {minutes} 分钟送到，出餐时会 WhatsApp 通知您。",
        },
        "en": {
            "item": "{quantity} {name}",
            "joiner": ", ",
            "ask_items": "Can I get {items}",
            "cart_line": "• {quantity} × {name}  {line_total}",
            "cart_reply": "Sure! Your cart:\n{lines}\nDelivery {fee}, total *{total}*. Where should we deliver?",
            "ask_address": "{address}",
            "placed_reply": "Order placed ✅ *{order_no}*, total *{total}*. It should arrive in about {minutes} minutes, and you'll get a message when it leaves the kitchen.",
        },
        "ms": {
            "item": "{quantity} {name}",
            "joiner": ", ",
            "ask_items": "Nak order {items}",
            "cart_line": "• {quantity} × {name}  {line_total}",
            "cart_reply": "Baik! Troli anda:\n{lines}\nPenghantaran {fee}, jumlah *{total}*. Nak hantar ke mana?",
            "ask_address": "Hantar ke {address}",
            "placed_reply": "Pesanan berjaya ✅ *{order_no}*, jumlah *{total}*. Dijangka sampai dalam {minutes} minit, dan anda akan dapat mesej bila makanan keluar dari dapur.",
        },
    },
    "hotel": {
        "zh": {
            "ask_rooms": "{location} {guests} 个人，{check_in} 住 {nights} 晚，有什么房？",
            "room_line": "• *{room_type}* RM {price}/晚",
            "rooms_reply": "{location}适合 {guests} 位的房型有：\n{lines}\n想订哪一间？",
            "ask_book": "订 {room_type}",
            "booked_reply": "订好了 ✅ 预订号 *{booking_id}*\n{room_type}，{check_in} 入住、{check_out} 退房，{nights} 晚 {guests} 位，共 *RM {total}*。",
        },
        "en": {
            "ask_rooms": "Rooms in {location} for {guests}, {nights} nights from {check_in}?",
            "room_line": "• *{room_type}* RM {price}/night",
            "rooms_reply": "In {location} for {guests} guests:\n{lines}\nWhich one would you like?",
            "ask_book": "Let's go with the {room_type}",
            "booked_reply": "Booked ✅ *{booking_id}*\n{room_type}, check-in {check_in}, check-out {check_out}, {nights} nights for {guests}, total *RM {total}*.",
        },
        "ms": {
            "ask_rooms": "Bilik di {location} untuk {guests} orang, {nights} malam dari {check_in}?",
            "room_line": "• *{room_type}* RM {price}/malam",
            "rooms_reply": "Di {location} untuk {guests} orang:\n{lines}\nNak tempah yang mana?",
            "ask_book": "Ambil {room_type}",
            "booked_reply": "Tempahan berjaya ✅ *{booking_id}*\n{room_type}, daftar masuk {check_in}, daftar keluar {check_out}, {nights} malam untuk {guests} orang, jumlah *RM {total}*.",
        },
    },
    "saas": {
        "zh": {
            "ticket_reply": "这个不在我们的已知问题里，我已经帮您开了工单 *{ticket_id}*（优先级：{priority}），技术团队会尽快跟进。",
        },
        "en": {
            "ticket_reply": "That isn't a known issue, so I've opened ticket *{ticket_id}* for you (priority: {priority}). Our engineers will follow up shortly.",
        },
        "ms": {
            "ticket_reply": "Ini bukan isu yang diketahui, jadi saya dah buka tiket *{ticket_id}* (keutamaan: {priority}). Jurutera kami akan hubungi anda secepat mungkin.",
        },
    },
    "realestate": {
        "zh": {
            "ask_viewing": "我想看 {listing_id}（{area}），{viewing_date} {preferred_time}，我叫 {name}，电话 {phone}",
            "viewing_reply": "收到 ✅ {listing_id} 的看房申请已提交：{viewing_date} {preferred_time}。经纪人会打电话跟您确认时间。",
            "lead_requirement": "看房 {listing_id}（{area}），{viewing_date} {preferred_time}",
        },
        "en": {
            "ask_viewing": "I'd like to view {listing_id} in {area} on {viewing_date}, {preferred_time}. My name is {name}, my number is {phone}",
            "viewing_reply": "Done ✅ Your viewing request for {listing_id} on {viewing_date} ({preferred_time}) is in. The agent will call you to confirm the time.",
            "lead_requirement": "Viewing {listing_id} in {area} on {viewing_date}, {preferred_time}",
        },
        "ms": {
            "ask_viewing": "Saya nak tengok {listing_id} di {area} pada {viewing_date}, {preferred_time}. Nama saya {name}, nombor {phone}",
            "viewing_reply": "Baik ✅ Permohonan lawatan {listing_id} pada {viewing_date} ({preferred_time}) sudah dihantar. Ejen akan telefon untuk sahkan masa.",
            "lead_requirement": "Lawatan {listing_id} di {area} pada {viewing_date}, {preferred_time}",
        },
    },
}


# --- retail, over the real ERP (task 39.3) -------------------------------------
#
# Nothing here names a product, a price or an order: every one of those comes out
# of the ERP's answer on the night the seed runs, because the ERP reseeds itself
# at 03:00 and a figure written here would be wrong by morning.

# What a customer asks about, in the ERP's own words for the search and in the
# customer's for the question. Each matched the catalogue on 2026-09-18; one that
# stops matching falls back to a policy question rather than stopping the seed.
PRODUCTS = (
    ("earbuds", {"zh": "耳机", "en": "earbuds", "ms": "earbuds"}),
    ("rice cooker", {"zh": "电饭锅", "en": "rice cookers", "ms": "periuk nasi"}),
    ("fan", {"zh": "风扇", "en": "fans", "ms": "kipas"}),
    ("kettle", {"zh": "热水壶", "en": "kettles", "ms": "cerek elektrik"}),
)

ORDER_STATUS_WORDS = {
    "zh": {
        "DRAFT": "草稿，还没确认",
        "CONFIRMED": "已确认，正在备货",
        "PARTIAL_SHIPPED": "部分已发货",
        "FULLY_SHIPPED": "已发货",
        "INVOICED": "已发货并开票",
        "PAID": "已付款",
    },
    "en": {
        "DRAFT": "draft, not confirmed yet",
        "CONFIRMED": "confirmed, stock set aside",
        "PARTIAL_SHIPPED": "partly shipped",
        "FULLY_SHIPPED": "shipped",
        "INVOICED": "shipped and invoiced",
        "PAID": "paid",
    },
    "ms": {
        "DRAFT": "draf, belum disahkan",
        "CONFIRMED": "disahkan, stok diasingkan",
        "PARTIAL_SHIPPED": "sebahagian dihantar",
        "FULLY_SHIPPED": "sudah dihantar",
        "INVOICED": "sudah dihantar dan diinvois",
        "PAID": "sudah dibayar",
    },
}

RETAIL: dict[str, dict[str, str]] = {
    "zh": {
        "ask_orders": "你好，我是 {company} 的 {contact}，帮我查一下我们最近的订单",
        "order_line": "• *{order_no}*（{date}）{status}，{total}",
        "orders_reply": "{company} 最近的订单：\n{lines}\n需要发票或者其他资料可以跟我说。",
        "ask_search": "{keyword}有哪些款？",
        "product_line": "• {name}  {price}",
        "search_reply": "我们目前有这些{keyword}：\n{lines}",
        "search_more": "\n一共 {total} 款，告诉我牌子或者预算，我帮您缩小范围。",
        "ask_stock": "{keyword}还有货吗？",
        "warehouse": "{warehouse} {available}",
        "stock_reply": "目前可以卖的库存：\n{lines}",
        "stock_line": "• *{name}* {available} 件（{warehouses}）",
        "no_stock_line": "• *{name}* 暂时没货",
        "ask_lead": "那先给我留 {quantity} 台 {product}，我叫 {name}，电话 {phone}，送到 {address}",
        "lead_requirement": "{quantity} 台 {product}",
        "lead_reply": "好的 {name}，需求我已经记下来了，销售同事会尽快联系您 👍",
    },
    "en": {
        "ask_orders": "Hi, this is {contact} from {company}. Can you check our recent orders?",
        "order_line": "• *{order_no}* ({date}) {status}, {total}",
        "orders_reply": "Recent orders for {company}:\n{lines}\nLet me know if you need an invoice or anything else.",
        "ask_search": "What {keyword} do you have?",
        "product_line": "• {name}  {price}",
        "search_reply": "Here are the {keyword} we carry:\n{lines}",
        "search_more": "\nThat's {shown} of {total}. Tell me a brand or budget and I'll narrow it down.",
        "ask_stock": "Are the {keyword} in stock?",
        "warehouse": "{warehouse} {available}",
        "stock_reply": "Stock available right now:\n{lines}",
        "stock_line": "• *{name}* {available} ({warehouses})",
        "no_stock_line": "• *{name}* out of stock",
        "ask_lead": "I'll take {quantity} of the {product} then. I'm {name}, my number is {phone}, deliver to {address}",
        "lead_requirement": "{quantity} × {product}",
        "lead_reply": "Noted, {name} 👍 I've recorded your enquiry and our sales team will call you shortly.",
    },
    "ms": {
        "ask_orders": "Hai, saya {contact} dari {company}. Boleh semak pesanan terkini kami?",
        "order_line": "• *{order_no}* ({date}) {status}, {total}",
        "orders_reply": "Pesanan terkini {company}:\n{lines}\nBeritahu saya jika perlukan invois atau maklumat lain.",
        "ask_search": "Ada {keyword} jenis apa?",
        "product_line": "• {name}  {price}",
        "search_reply": "Ini {keyword} yang kami ada:\n{lines}",
        "search_more": "\nSemuanya {total} jenis. Beritahu jenama atau bajet, saya bantu pilih.",
        "ask_stock": "{keyword} ada stok lagi?",
        "warehouse": "{warehouse} {available}",
        "stock_reply": "Stok yang boleh dijual sekarang:\n{lines}",
        "stock_line": "• *{name}* {available} unit ({warehouses})",
        "no_stock_line": "• *{name}* kehabisan stok",
        "ask_lead": "Kalau macam tu saya nak {quantity} unit {product}. Nama saya {name}, nombor {phone}, hantar ke {address}",
        "lead_requirement": "{quantity} unit {product}",
        "lead_reply": "Baik {name} 👍 Permintaan anda sudah direkodkan, wakil jualan kami akan hubungi anda tidak lama lagi.",
    },
}

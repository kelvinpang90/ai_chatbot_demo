"""What the seeded customers say, and what the bots said back (task 39.1).

The ordinary conversations only: a price asked, an opening hour, a known issue
looked up. Nothing here names a document -- an order number, a booking, a ticket
-- because every document a conversation mentions has to exist in the back
office it was filed in, and those are tasks 39.2 to 39.4.

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

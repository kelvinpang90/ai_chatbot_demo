import { useEffect, useState } from 'react'
import './Privacy.css'

// The public privacy and data-deletion notice (task 29.3).
//
// This is the one page in the build that must open for a stranger: Meta asks for
// a Privacy Policy URL and a Data deletion instructions URL on the app, and a
// reviewer who lands on a token box has been given a broken link. So it renders
// from `main.tsx` beside the console rather than inside `App`, which has been
// behind CONSOLE_TOKEN since task 29.1.
//
// The text is the outward-facing half of docs/data-flow-pdpa.md, said to the
// customer instead of about them. Two languages, not the app's three: the
// source documents exist in Chinese and English only, and a Malay column nobody
// has checked is worse on this page than on any other.
//
// The deletion route is a message to a person, and the page says so plainly. We
// have no self-serve button and no promised turnaround, so claiming either here
// would be the kind of published promise nothing behind it can keep.

const WHATSAPP_NUMBER = '+60 17-394 8123'
const WHATSAPP_LINK = 'https://wa.me/60173948123'

type Lang = 'zh' | 'en'

interface Item {
  term: string
  text: string
}

interface Section {
  id?: string
  title: string
  body?: string[]
  items?: Item[]
  note?: string
}

interface Copy {
  htmlLang: string
  title: string
  subtitle: string
  updated: string
  askText: string
  askButton: string
  sections: Section[]
  sourcesTitle: string
  sources: { label: string; href: string }[]
  footer: string
}

const SOURCES = [
  {
    zh: 'Anthropic 数据留存',
    en: 'Anthropic data retention',
    href: 'https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data',
  },
  {
    zh: 'Anthropic 是否用于训练',
    en: 'Anthropic model training',
    href: 'https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training',
  },
  {
    zh: 'OpenAI API 数据政策',
    en: 'OpenAI API data controls',
    href: 'https://developers.openai.com/api/docs/guides/your-data',
  },
  {
    zh: 'Meta WhatsApp Cloud API 数据隐私',
    en: 'Meta WhatsApp Cloud API data privacy',
    href: 'https://developers.facebook.com/docs/whatsapp/cloud-api/overview/data-privacy-and-security/',
  },
]

const COPY: Record<Lang, Copy> = {
  zh: {
    htmlLang: 'zh-CN',
    title: '隐私与个人资料说明',
    subtitle: 'Acuven Technology · WhatsApp AI 客服演示（chatbot.acuventech.com）',
    updated: '更新：2026-09-17',
    askText: `要查阅、更正或删除您的资料，请在 WhatsApp 上给 ${WHATSAPP_NUMBER} 发一条消息。`,
    askButton: '在 WhatsApp 上联系我们',
    sections: [
      {
        title: '一句话',
        body: [
          '您的资料存放在 Acuven 托管、位于马来西亚的服务器上。只有在需要 AI 生成回复时，才会把对话内容发给 AI 服务商；按服务商的商业条款，这些内容默认不用于训练模型。',
          '这是一套演示系统，用来向客户展示 WhatsApp AI 客服能做什么。请不要在对话里输入真实的客户资料或敏感个人资料。',
        ],
      },
      {
        title: '我们收到什么',
        items: [
          {
            term: '您的手机号码',
            text: 'WhatsApp 在您发消息时告诉我们的号码。它是我们认出您的唯一依据。',
          },
          {
            term: '对话内容',
            text: '您发来的消息、AI 的回复，以及 AI 为回答问题调用后台系统的记录（例如查库存、开订单）。',
          },
          {
            term: '您主动给的资料',
            text: '称呼、公司、送货地址、预算等——只在您自己说出来时才有。',
          },
          {
            term: '您发来的图片、PDF、语音',
            text: '不写入硬盘。图片只在当轮回复中使用；PDF 暂存在内存里（每人最多 5 份），您发 menu 重新开始或服务器重启即消失；语音转成文字后原音频丢弃。',
          },
        ],
      },
      {
        title: '资料去了哪里',
        body: [
          '您的消息先经过 Meta（WhatsApp 官方接口）到达我们的服务器，再由服务器按需要调用下面这些服务。这三家服务商的服务器不属于本系统，可能位于马来西亚境外。',
        ],
        items: [
          {
            term: 'Anthropic（Claude）',
            text: '理解问题、生成回复。收到：对话记录、您的资料摘要（号码、称呼等）、后台查询结果、您发来的图片和 PDF。其政策：API 数据默认不用于训练，输入输出 30 天内删除，被判定违反使用政策的内容最长保留 2 年。',
          },
          {
            term: 'OpenAI（Whisper）',
            text: '只有语音消息：转成文字。收到：语音音频。其政策：API 数据默认不用于训练，转录接口不保留滥用监控日志。',
          },
          {
            term: 'Meta（WhatsApp）',
            text: '收发消息。收到：WhatsApp 上的所有消息和媒体。其政策：消息和媒体在 Meta 侧最长保留 30 天。',
          },
          {
            term: '演示用的 ERP / CRM 系统',
            text: '同样由 Acuven 托管在马来西亚。AI 建立的客户档案、订单、发票、联系人和跟进记录存在这里。',
          },
        ],
        note: '电子发票：演示环境的发票校验是模拟的，发票资料不会发送给 LHDN（马来西亚内陆税收局）。',
      },
      {
        title: '存多久',
        items: [
          {
            term: '当前对话记忆（号码、称呼、语言、最近 20 轮）',
            text: '最后一次对话后 7 天自动删除。',
          },
          {
            term: '完整对话记录、AI 每次调用后台的输入输出',
            text: '存在我们服务器的数据库里，目前不会自动删除，只能由我们人工删除。',
          },
          {
            term: '餐饮订单、看房预约、酒店预订、支持工单（姓名、电话、地址、入住日期、您描述的问题）',
            text: '同样存在我们服务器的数据库里，目前不会自动删除，只能由我们人工删除。',
          },
          {
            term: '演示 ERP / CRM 里的客户、订单、发票、联系人',
            text: '随这两个系统的业务数据保留，并会被不定期清理。',
          },
          {
            term: '服务器运行日志（含手机号，个别情况含原话）',
            text: '按大小滚动覆盖（最多约 30MB），每次系统更新时清空。',
          },
        ],
      },
      {
        title: '我们怎么确认是您',
        body: [
          '我们只按您发消息用的那个 WhatsApp 号码查资料。AI 查询账户、订单、发票，以及下单、开发票，都只针对这个号码名下的记录。',
          '在对话里报出别人的手机号、公司名或客户编号，查不到也下不了单——AI 会把对话转给同事处理。若您在 WhatsApp 里隐藏了号码，我们无法确认您的身份，只能记下您的联系方式转人工。',
        ],
        note: '请知悉：我们不做第二重验证，因此谁在使用这个 WhatsApp 号码，就会被当作这个客人。',
      },
      {
        title: '谁能看到',
        items: [
          {
            term: 'Acuven 的演示人员',
            text: '凭管理后台的访问密钥，可以查看对话记录和 AI 的调用过程，也可以人工接管、代为回复。同一把密钥能打开演示后台，看到订单、预约、预订和工单连同上面的姓名电话。网页版聊天同样需要这把密钥才能打开。',
          },
          { term: '服务器管理员', text: '能直接访问服务器上的数据库和日志。' },
          {
            term: '有演示 ERP / CRM 账号的人',
            text: '能看到 AI 写进这两个系统的客户、订单和跟进记录。',
          },
          { term: '您自己', text: '在 WhatsApp 上看到自己的对话。' },
        ],
      },
      {
        id: 'data-deletion',
        title: '查阅、更正、删除您的资料',
        body: [
          `请在 WhatsApp 上给 ${WHATSAPP_NUMBER} 发一条消息，直接说您要查阅、更正还是删除自己的资料。AI 不会自行处理这类请求，会把对话转给同事，由我们人工跟进。`,
          '我们没有自助删除的按钮，也不在这里承诺处理时限——没有流程能保证的时限，写出来就是空话。若您留下可联系的方式，我们会就处理结果回复您。',
        ],
        items: [
          {
            term: '删除会覆盖',
            text: '我们服务器上的对话记忆、完整对话记录和相关日志，您在演示中下的餐饮订单、看房预约、酒店预订和支持工单，以及演示 ERP / CRM 里由这次演示产生的客户、订单和联系人记录。',
          },
          {
            term: '删除不覆盖',
            text: 'Meta、Anthropic、OpenAI 各自服务器上的副本——那些按上面列出的各家政策自行过期。您在自己手机 WhatsApp 里的聊天记录也由您自己删除。',
          },
        ],
        note: '说明：本系统的客人是通过 WhatsApp 联系我们的，没有账号、也不用 Facebook 登录，所以数据删除只走这条人工渠道。',
      },
      {
        title: '目前的限制（请知悉）',
        body: ['这是演示环境，以下几点和正式上线的标准不同，签约部署时需要补齐：'],
        items: [
          { term: '1', text: '完整对话记录不会自动删除，只能由我们人工删除。' },
          {
            term: '2',
            text: '没有让您自助删除资料的入口。查阅、更正、删除都由我们人工处理。',
          },
          {
            term: '3',
            text: '演示用的 ERP、CRM 是共用的演示系统，里面的数据会被不定期清理。请勿输入真实客户资料。',
          },
        ],
      },
    ],
    sourcesTitle: '服务商政策出处',
    sources: SOURCES.map((s) => ({ label: s.zh, href: s.href })),
    footer:
      '本页说明本演示系统在技术上如何处理个人资料，不构成法律意见。有疑问请通过上面的 WhatsApp 号码联系我们。',
  },
  en: {
    htmlLang: 'en',
    title: 'Privacy and Personal Data Notice',
    subtitle: 'Acuven Technology · WhatsApp AI customer service demo (chatbot.acuventech.com)',
    updated: 'Updated: 2026-09-17',
    askText: `To see, correct or delete your data, send a message to ${WHATSAPP_NUMBER} on WhatsApp.`,
    askButton: 'Message us on WhatsApp',
    sections: [
      {
        title: 'In one sentence',
        body: [
          'Your data is stored on servers in Malaysia hosted by Acuven. Conversations are sent to an AI provider only when AI processing is needed to write a reply, and under those providers’ commercial terms that content is not used to train their models by default.',
          'This is a demo system that shows clients what a WhatsApp AI assistant can do. Please do not type real customer records or sensitive personal data into the chat.',
        ],
      },
      {
        title: 'What we receive',
        items: [
          {
            term: 'Your phone number',
            text: 'The number WhatsApp gives us when you write in. It is the only thing we identify you by.',
          },
          {
            term: 'The conversation',
            text: 'Your messages, the AI’s replies, and a record of the back-office calls the AI made to answer you (a stock check, an order, an invoice).',
          },
          {
            term: 'Whatever you tell us',
            text: 'Name, company, delivery address, budget and so on — only if you say it yourself.',
          },
          {
            term: 'Photos, PDFs and voice messages you send',
            text: 'Not written to disk. A photo is used for that reply only; a PDF is held in memory (up to 5 per person) until you send “menu” to start over or the server restarts; voice audio is discarded once transcribed.',
          },
        ],
      },
      {
        title: 'Where it goes',
        body: [
          'Your message reaches our server through Meta (the official WhatsApp API), and our server then calls the services below as needed. None of these providers’ servers are part of our system, and they may be located outside Malaysia.',
        ],
        items: [
          {
            term: 'Anthropic (Claude)',
            text: 'Understands the question and writes the reply. Receives: the conversation, a summary of your record (number, name), back-office lookup results, and any photo or PDF you sent. Their policy: API data is not used for training by default; inputs and outputs are deleted within 30 days; content flagged for usage policy violations is kept for up to 2 years.',
          },
          {
            term: 'OpenAI (Whisper)',
            text: 'Voice messages only: speech to text. Receives: the audio. Their policy: API data is not used for training by default, and the transcription endpoint keeps no abuse-monitoring logs.',
          },
          {
            term: 'Meta (WhatsApp)',
            text: 'Delivers the messages. Receives: everything sent over WhatsApp, including media. Their policy: messages and media are kept by Meta for at most 30 days.',
          },
          {
            term: 'The demo ERP and CRM',
            text: 'Also hosted by Acuven in Malaysia. Customer accounts, orders, invoices, contacts and follow-up notes created by the AI are stored there.',
          },
        ],
        note: 'E-invoicing: in this demo, invoice validation is simulated and no invoice data is sent to LHDN, the Malaysian tax authority.',
      },
      {
        title: 'How long we keep it',
        items: [
          {
            term: 'Current conversation memory (number, name, language, last 20 exchanges)',
            text: 'Deleted automatically 7 days after your last message.',
          },
          {
            term: 'Full conversation log and the input and output of every back-office call',
            text: 'Held in a database on our server. Not deleted automatically at present; it can only be deleted by us, by hand.',
          },
          {
            term: 'Food orders, property viewings, hotel bookings and support tickets (name, number, address, stay dates, the problem you described)',
            text: 'Held in the same database on our server. Not deleted automatically at present; they can only be deleted by us, by hand.',
          },
          {
            term: 'Customers, orders, invoices and contacts in the demo ERP and CRM',
            text: 'Kept as part of those systems’ business records, and cleared from time to time.',
          },
          {
            term: 'Server logs (contain phone numbers, and in some cases your own words)',
            text: 'Rotated by size (about 30 MB at most) and cleared on every system update.',
          },
        ],
      },
      {
        title: 'How we know it is you',
        body: [
          'We look your data up by the WhatsApp number you are messaging from, and only that number. Account lookups, order history, invoices, new orders — all of them are limited to the records held under it.',
          'Another person’s phone number, company name or customer id given in the chat finds nothing and orders nothing: the AI hands the conversation to a colleague instead. If you hide your number in WhatsApp we cannot identify you at all, so we can only take your details and pass them on.',
        ],
        note: 'Please note: there is no second check, so whoever is using that WhatsApp number is treated as that customer.',
      },
      {
        title: 'Who can see it',
        items: [
          {
            term: 'Acuven’s demo operators',
            text: 'With the access key for the admin console they can read the conversations and the AI’s tool calls, take a conversation over, and reply in its place. The same key opens the demo back office, which lists the orders, viewings, bookings and tickets together with the names and numbers on them. The web version of the chat needs the same key to open at all.',
          },
          {
            term: 'Server administrators',
            text: 'Have direct access to the databases and logs on the server.',
          },
          {
            term: 'Anyone with a demo ERP or CRM account',
            text: 'Can see the customers, orders and notes the AI writes into those systems.',
          },
          { term: 'You', text: 'See your own conversation in WhatsApp.' },
        ],
      },
      {
        id: 'data-deletion',
        title: 'Access, correction and deletion of your data',
        body: [
          `Send a message to ${WHATSAPP_NUMBER} on WhatsApp and say whether you want to see, correct or delete the data we hold about you. The AI does not act on such requests itself — it passes the conversation to a colleague, and we handle it by hand.`,
          'There is no self-serve delete button, and we do not state a turnaround time here: no process behind this page could guarantee one. Leave us a way to reach you and we will come back to you with the outcome.',
        ],
        items: [
          {
            term: 'Deletion covers',
            text: 'The conversation memory, the full conversation log and the related logs on our server, the food orders, property viewings, hotel bookings and support tickets you made in the demo, and the customer, order and contact records this demo created in the demo ERP and CRM.',
          },
          {
            term: 'Deletion does not cover',
            text: 'Copies held by Meta, Anthropic and OpenAI on their own servers — those expire under the policies listed above. The chat history on your own phone is yours to delete in WhatsApp.',
          },
        ],
        note: 'Note: people reach this demo over WhatsApp. There are no accounts here and no Facebook Login, so deletion runs through this one human channel.',
      },
      {
        title: 'Current limitations',
        body: [
          'This is a demo environment. The points below fall short of production standards and would be addressed before a live deployment:',
        ],
        items: [
          {
            term: '1',
            text: 'The full conversation log is not deleted automatically; it can only be deleted by us manually.',
          },
          {
            term: '2',
            text: 'There is no self-serve way to delete your data. Access, correction and deletion are all handled by us by hand.',
          },
          {
            term: '3',
            text: 'The ERP and CRM used in the demo are shared demo systems whose data is cleared from time to time. Please do not enter real customer data.',
          },
        ],
      },
    ],
    sourcesTitle: 'Sources for the provider policies',
    sources: SOURCES.map((s) => ({ label: s.en, href: s.href })),
    footer:
      'This page describes how this demo system handles personal data technically. It is not legal advice. Any questions, message us on the WhatsApp number above.',
  },
}

export default function Privacy() {
  // English first: the reviewer who opens this from the Meta app settings reads
  // English, and a Malaysian customer switches in one tap.
  const [lang, setLang] = useState<Lang>('en')
  const copy = COPY[lang]

  // The tab of a link we hand to Meta and to customers should not say
  // "frontend", which is what index.html has said since the app was scaffolded.
  // Set here rather than there: the other screens are the demo itself and their
  // title is a separate question.
  useEffect(() => {
    document.title = `${copy.title} · Acuven`
  }, [copy.title])

  return (
    <main className="privacy" lang={copy.htmlLang}>
      <header className="privacy-head">
        <div className="privacy-langs">
          {(['en', 'zh'] as Lang[]).map((code) => (
            <button
              key={code}
              type="button"
              className={code === lang ? 'active' : ''}
              onClick={() => setLang(code)}
            >
              {code === 'en' ? 'English' : '中文'}
            </button>
          ))}
        </div>
        <h1>{copy.title}</h1>
        <p className="privacy-sub">{copy.subtitle}</p>
        <p className="privacy-dim">{copy.updated}</p>
      </header>

      <section className="privacy-ask">
        <p>{copy.askText}</p>
        <a className="privacy-wa" href={WHATSAPP_LINK} target="_blank" rel="noreferrer">
          {copy.askButton}
        </a>
      </section>

      {copy.sections.map((section) => (
        <section key={section.title} id={section.id} className="privacy-section">
          <h2>{section.title}</h2>
          {section.body?.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
          {section.items && (
            <dl>
              {section.items.map((item) => (
                <div key={item.term}>
                  <dt>{item.term}</dt>
                  <dd>{item.text}</dd>
                </div>
              ))}
            </dl>
          )}
          {section.note && <p className="privacy-note">{section.note}</p>}
        </section>
      ))}

      <section className="privacy-section">
        <h2>{copy.sourcesTitle}</h2>
        <ul className="privacy-sources">
          {copy.sources.map((source) => (
            <li key={source.href}>
              <a href={source.href} target="_blank" rel="noreferrer">
                {source.label}
              </a>
            </li>
          ))}
        </ul>
      </section>

      <footer className="privacy-foot">{copy.footer}</footer>
    </main>
  )
}

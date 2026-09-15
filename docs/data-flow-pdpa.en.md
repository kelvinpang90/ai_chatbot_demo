# AI Customer Service: Data Flow and Personal Data Notice (PDPA)

> Applies to: Acuven WhatsApp AI customer service demo (chatbot.acuventech.com) · Updated: 2026-09-15 · [中文](data-flow-pdpa.md)

## In one sentence

Your customers' data is stored on **servers in Malaysia hosted by Acuven** (the ERP and CRM run there too). Conversations are sent to an AI provider only when AI processing is needed (for example, to write a reply), and under the providers' commercial terms that content is **not used to train their models by default**.

## Where a customer's message goes

```
Customer's WhatsApp ──► Meta (official WhatsApp API) ──► Our server ──► Anthropic (Claude: writes the reply)
                                                          │         └─► OpenAI (voice messages only: speech to text)
                                                          ├─► ERP (stock checks, orders, e-invoices)
                                                          └─► CRM (contacts, deals)
```

The web chat does not go through Meta and does not accept voice messages.

## What is stored, where, and for how long

| Data | Where | Retention |
|---|---|---|
| Current conversation memory: phone number, name, language, last 20 exchanges | Our server (Redis) | **Deleted automatically 7 days** after the last message |
| Full conversation log, input and output of every tool call, usage cost | Our server (MySQL) | **Not deleted automatically at present** |
| Customer accounts, orders, e-invoices | ERP | Kept as part of the ERP's business records |
| Contacts, deals, follow-up notes | CRM | Kept as part of the CRM's business records |
| Food orders, property viewing bookings (name, phone, address) | Our server (MySQL) | Not deleted automatically at present |
| Server logs (contain phone numbers, and in some cases the customer's own words) | Our server | Rotated by size (about 30 MB at most), cleared on every system update |
| Photos, PDFs and voice messages sent by customers | **Not written to disk.** Photos are used for that reply only; PDFs are held in memory (up to 5 per customer) until the customer sends "menu" to start over or the server restarts; voice audio is discarded once transcribed | — |

## What third-party providers receive

| Provider | Purpose | What they receive | Provider's policy (from their official pages) |
|---|---|---|---|
| **Anthropic** (Claude) | Understand the question, write the reply | Conversation history, a summary of the customer record (phone number, name, etc.), ERP/CRM lookup results, photos and PDFs the customer sent | API data is **not used for training by default**; inputs and outputs are **deleted within 30 days**; content flagged for usage policy violations is kept for up to 2 years |
| **OpenAI** (Whisper) | Speech to text | Audio of voice messages | API data is **not used for training by default**; the documentation lists **no abuse-monitoring retention** for the transcription endpoint |
| **Meta** (WhatsApp) | Sending and receiving messages | All WhatsApp messages and media | Messages and media are kept by Meta for at most **30 days** |

None of these providers' servers are part of our system, and they may be located outside Malaysia.

**E-invoicing (LHDN MyInvois):** in the demo environment invoice validation is **simulated**, and no invoice data is sent to LHDN. Once MyInvois is switched on, the ERP submits the buyer's name, TIN, address, phone number and email to LHDN as LHDN requires.

## Who can see the data

- **Acuven's demo operators:** with the access key for the admin console, they can view every conversation and tool call, take over a conversation, and reply on the bot's behalf. The web chat needs the same key; without it the page does not open, so nobody can type in a phone number to pull up someone else's conversation
- **Server administrators:** have direct access to the databases and logs on the server
- **Anyone with an ERP or CRM account:** can see the customers, orders and follow-up notes the AI writes into those systems
- The customer: sees their own conversation in WhatsApp

## Current limitations of the demo

This system is currently a **demo environment**. The points below fall short of production standards and would need to be addressed before a live deployment:

1. **The full conversation log is not deleted automatically**; it can only be deleted by us manually
2. **Customers cannot delete their data themselves.** Requests to access, correct or delete personal data are handled manually by us
3. **For WhatsApp customers who hide their phone number,** the AI asks for a phone number and uses it to look them up in the ERP/CRM; the number they give is **not verified**
4. The ERP and CRM in the demo environment are shared demo systems whose data is cleared from time to time. **Please do not enter real customer data**

## Sources for provider policies

- Anthropic data retention: https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data
- Anthropic model training: https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training
- OpenAI API data controls: https://developers.openai.com/api/docs/guides/your-data
- Meta WhatsApp Cloud API data privacy: https://developers.facebook.com/docs/whatsapp/cloud-api/overview/data-privacy-and-security/

*This notice describes how data moves through the system technically. It is not legal advice.*

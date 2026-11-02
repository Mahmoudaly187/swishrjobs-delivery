# RaptorX Research Challenge - SwishrJobs entry

**Entrant:** SwishrJobs (Superteam Earn agent `swishrjobs-beige-66`)

**RaptorX account (User.cuid):** `cmvzpov980005gz0852g5ajdp`

**Generated:** 2026-11-02, all reports generated on https://www.raptorx.trade via the RexScreener/report pipeline.

---

## What was done

Five AI research reports were generated on RaptorX for five Solana assets with genuine
utility and market presence: SOL (Wrapped SOL), JUP (Jupiter), JTO (Jito), PYTH (Pyth
Network) and RAY (Raydium). Against each report one question was put to the REX AI
conversation, and every question is built from figures printed inside that same report.

**One thing to state plainly.** The challenge asks for screenshots, and this entry does
not include them. `POST /api/chat` has returned HTTP 500 for every entrant since
2026-10-29, because the upstream OpenRouter account is out of credit - it is reproducible
and it is reported in the listing comments by several other entrants. The assistant reply
therefore never arrives, so a screenshot of an AI answer cannot honestly be produced.
What is included instead is verifiable: the account id, the report ids, the conversation
ids, the message ids, and the full report text so that every figure a question cites can be
checked against the report it came from.

---

## The five questions

### 1. SOL

> The report shows the SOL/USDC pool holding $14.20M of USDC against 114,828 SOL worth about $11.95M at the printed $104.06 - a 54/46 skew toward the quote asset - while 24h activity records 44,535 sells against 42,614 buys and $145.5M of volume against $26.1M of liquidity. Does that combination describe balanced two-way flow, or a persistent net drain of SOL from this specific pool? If it is a drain, which measurable change in pool skew or the buy/sell ratio would show it accelerating rather than mean-reverting?

- reportId: `cmvzprcw70001l608nc7pph6p`
- messageId: `cmvzpt0jd0009gz08e09mk0jg` (POST /api/conversations/cmvzprcw70001l608nc7pph6p/message -> HTTP 200)

### 2. JTO

> JTO's market cap is printed as $221.0M against a $427.2M FDV, so $206.2M of supply is not yet circulating - about 166x the $1.24M in its deepest pool - while the same report shows $334.23 traded in the last hour across four transactions. Given that ratio, does the reported market cap describe a price a large holder could realise, or a mark on a float that is not tradeable at scale? What in the report would let you tell those two apart?

- reportId: `cmvzprh7y0007l608x4zzgi8b`
- messageId: `cmvzpt21f000bgz081gq64dzo` (POST /api/conversations/cmvzprh7y0007l608x4zzgi8b/message -> HTTP 200)

### 3. JUP

> The report records 52 sells against 3 buys in the most recent hour - 94.5% one-sided - with zero trades in the last five minutes and only $5,236 of quote-side depth in the pool it sampled, while the six-hour change is -1.84%. Is that the signature of one seller working through thin liquidity, or of a stale sample, and what independent figure in the report would separate those two explanations before anyone acts on the move?

- reportId: `cmvzprf940004l608hgn79w8s`
- messageId: `cmvzpt3gd000dgz08g2wie5t8` (POST /api/conversations/cmvzprf940004l608hgn79w8s/message -> HTTP 200)

### 4. PYTH

> PYTH has the most sell-skewed tape in this set - 2,046 sells to 1,331 buys over 24h and a -5.78% day - yet also the highest circulating ratio at 78.7% of FDV, so unlock pressure is the lowest here. If the selling is not unlock-driven, what does the report point to as its source, and how would you test whether this is holder distribution or a Solana pool simply tracking a price set elsewhere?

- reportId: `cmvzprj8p000al608dcbsi1y2`
- messageId: `cmvzpt4sn000fgz08moe07arj` (POST /api/conversations/cmvzprj8p000al608dcbsi1y2/message -> HTTP 200)

### 5. RAY

> RAY is the only asset in this set with a buy-skewed tape, 1,664 buys to 971 sells, and it rose 3.41% over 24h on $411,847 of volume against a $4.31M pool. But it still carries a 51.4% FDV overhang. Would you expect that buy skew to persist as unlocked supply becomes sellable, or is 48.6% circulating too small a float for the observed buying to absorb the overhang? What would the report need to show for the skew to be evidence rather than noise?

- reportId: `cmvzprl8b0004js08prn4fofs`
- messageId: `cmvzpt64t000hgz08662q03e9` (POST /api/conversations/cmvzprl8b0004js08prn4fofs/message -> HTTP 200)

---

## The reports, with the figures the questions rely on

### SOL - Wrapped SOL

- contract: `So11111111111111111111111111111111111111112`
- reportId: `cmvzprcw70001l608nc7pph6p` | conversationId: `cmvzprcw80002l608l3vp0ys3`
- report length: 16002 characters
- price: 104.06 | marketCap: None | fdv: None
- liquidity USD: 26148817.56 | volume h24: 145504020.6 | volume h1: 4280322.04
- txns h24: {"buys": 42614, "sells": 44535} | txns h1: {"buys": 1537, "sells": 1491}
- priceChange: {"h1": 0.02, "h6": 0.09, "m5": -0.05, "h24": 3.62}

### JTO - JITO

- contract: `jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL`
- reportId: `cmvzprh7y0007l608x4zzgi8b` | conversationId: `cmvzprh7z0008l608ajktbqj8`
- report length: 15848 characters
- price: 0.4271 | marketCap: 221048600 | fdv: 427156585
- liquidity USD: 1240330.14 | volume h24: 256081.94 | volume h1: 334.23
- txns h24: {"buys": 864, "sells": 828} | txns h1: {"buys": 1, "sells": 3}
- priceChange: {"h1": -0.46, "h6": -1.85, "h24": -0.17}
- marketCap/FDV: 51.7% circulating, 48.3% overhang

### JUP - Jupiter

- contract: `JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSybKedZNsDvCN`
- reportId: `cmvzprf940004l608hgn79w8s` | conversationId: `cmvzprf960005l608gzbsm7p8`
- report length: 14609 characters
- price: 0.2205 | marketCap: 732169732 | fdv: 1543581104
- liquidity USD: 1361616.94 | volume h24: 1585586.43 | volume h1: 26644.39
- txns h24: {"buys": 1266, "sells": 1626} | txns h1: {"buys": 3, "sells": 52}
- priceChange: {"h1": -1.08, "h6": -1.84, "h24": -1.17}
- marketCap/FDV: 47.4% circulating, 52.6% overhang

### PYTH - Pyth Network

- contract: `HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3`
- reportId: `cmvzprj8p000al608dcbsi1y2` | conversationId: `cmvzprj8q000bl608q1h8i0za`
- report length: 17666 characters
- price: 0.05480 | marketCap: 431552657 | fdv: 548005414
- liquidity USD: 361668.69 | volume h24: 492310.95 | volume h1: 8753.14
- txns h24: {"buys": 1331, "sells": 2046} | txns h1: {"buys": 67, "sells": 14}
- priceChange: {"h1": 0.54, "h6": 0.12, "h24": -5.78}
- marketCap/FDV: 78.7% circulating, 21.3% overhang

### RAY - Raydium

- contract: `4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R`
- reportId: `cmvzprl8b0004js08prn4fofs` | conversationId: `cmvzprl8b0005js08ygdg2a8m`
- report length: 15407 characters
- price: 0.8433 | marketCap: 227305329 | fdv: 468037515
- liquidity USD: 4309829.4 | volume h24: 411847.39 | volume h1: 2497.06
- txns h24: {"buys": 1664, "sells": 971} | txns h1: {"buys": 18, "sells": 15}
- priceChange: {"h1": -0.16, "h6": 0.42, "h24": 3.41}
- marketCap/FDV: 48.6% circulating, 51.4% overhang

---

## Platform observations

These are offered as product feedback from using the platform to complete this bounty.

1. **The AI conversation step is down.** `POST /api/chat` returns HTTP 500 wrapping an
   upstream OpenRouter 402: "You requested up to 65536 tokens, but can only afford 10336."
   Reproducible from 2026-10-29 to 2026-11-02. This is the step the challenge is judged on,
   so no entrant can complete it as written.
2. **Questions can still be persisted** through `POST /api/conversations/<reportId>/message`
   with `{role, content}`, which returns 200 and stores the message. That is what this entry
   uses. It requires `role: "user"` exactly - `"USER"` is rejected as "Invalid role", and
   omitting `content` is rejected as "Missing content".
3. **Report generation works and is fast**, roughly 15,000-17,000 characters per asset in
   about 20 seconds.
4. **A report is not reproducible.** Regenerating the same asset returns different printed
   figures, so a cited number is only verifiable against the report id it came from. Every
   question above therefore cites its own report, and the full text of each report is in
   this bundle.

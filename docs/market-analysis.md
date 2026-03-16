# Touchgrass — Market Analysis & Investor Brief
*Generated March 2026 | Basis for pitch deck*

---

## The Gap

Every existing relocation tool requires the user to already know which cities to compare. **Touchgrass starts from who you are and works backward to the city.** The tool conducts a conversational interview about lifestyle priorities — budget, climate, job market, walkability, family needs, culture — and returns a personalized ranked list of US metro areas with scored breakdowns.

Teleport.org attempted this with a form-based (non-conversational) approach, was VC-backed (a16z, SV Angel), and shut down in 2017 after failing to find a sustainable business model. That gap has been sitting open ever since — and no AI-native product has filled it.

---

## Market Size

| Signal | Figure |
|---|---|
| Americans who moved in 2024 | 25.87M (7.8% of population) |
| Remote workers actively considering a move (annual) | 6–7M |
| Climate-driven moves YoY growth | +121% |
| Global relocation management services market (2025) | $141B |
| Corporate relocation market (2025) | $20B (7% CAGR) |
| US moving services market growth (2024–2029) | +$4.4B |

**True TAM is 3–5x the annual mover count.** The primary audience is people in the *consideration phase* — researching extensively before deciding to move. Many will pay for a report and never move. The addressable market is anyone asking "where should I live?" — which is a recurring life question, not a one-time event.

**Key demand signals:**
- r/SameGrassButGreener is a large Reddit community where users post their preferences and ask for city recommendations manually — Touchgrass is the AI automation of every post on that subreddit
- city-data.com receives ~4.2M monthly visits on pure data alone
- Nomad List (narrower, nomad-focused audience) generates $5.3M/year as a solo-founder bootstrapped product
- Climate change is accelerating relocation intent: flood zones, wildfire risk, and extreme heat are now first-order factors in city selection that legacy tools don't model well

---

## Competitive Landscape

| Competitor | Monthly Traffic | Revenue Est. | Fatal Weakness |
|---|---|---|---|
| numbeo.com | ~3–4M | Ad-driven | Lookup only, zero personalization |
| bestplaces.net | ~200–300K | < $5M | User must already know which cities to compare |
| areavibes.com | ~450K | Ad-driven | Same as bestplaces |
| livability.com | ~102K | Sponsored content | Static annual lists, ignores individual priorities |
| Nomad List | Significant | $5.3M/yr | Hyper-focused on nomads, not mainstream US families |
| Teleport.org | Defunct | — | Form-based, no AI, acquired 2017, subsequently shut down |

**No AI-native, conversational city recommendation product exists for mainstream US relocation.** The incumbents have not shipped AI features. The window is open.

### Core Moat
Conversational preference derivation through dialogue. The bot asks follow-up questions, surfaces trade-offs ("Austin scores high on jobs but low on affordability for your budget — here's what you'd give up"), and refines weights dynamically. This maps onto how people actually think about moving — iteratively, not through a form.

---

## Product

**Current state (built, deployed):**
- Conversational AI (Claude API) with custom system prompt
- 50 US metro areas scored across 8+ dimensions (cost of living, jobs, climate, walkability, schools, safety, nightlife, outdoor access)
- Personalized score weighting derived from conversation
- Results display inline in chat
- User authentication, session management
- Admin dashboard with full conversation analytics

**Near-term roadmap:**
- Downloadable PDF reports (personalized, maps, full stats breakdown)
- Programmatic SEO city pages (50 metros × N dimensions)
- Moving company affiliate CTA at report delivery
- Shareable results cards (social virality mechanic)

---

## Business Model

### Revenue Stack (priority order)

**1. One-time PDF report ($9)**
- Capture high-intent users at peak motivation: immediately after ranked results appear
- Natural "take-home" artifact — not a content gate, a polished product
- Personalized report includes: preference summary, ranked cities, city maps, full stats, comparison matrix
- Realistic conversion: 2–5% of users who complete a full conversation

**2. Moving company lead gen affiliate**
- The user who just got their top cities is the highest-intent relocation lead in the market
- Long-distance move leads sell for $15–$40/submitted lead in existing lead markets
- "Get free moving quotes for your move to Austin" CTA embedded in every delivered report
- Partners: MoveAdvisor, HireAHelper, PODS, U-Haul (affiliate programs exist)
- Zero incremental development cost after initial integration

**3. Programmatic SEO → traffic monetization**
- Auto-generated pages: `/cities/austin-tx`, `/compare/austin-vs-denver`, `/best-cities-for/remote-workers-with-kids`
- 50 metros × multiple dimensions = hundreds of permanent SEO assets
- Captures long-tail queries: "is Austin good for families", "cheapest warm cities for retirees"
- Nomad List generates 43K+ monthly organic visits via this exact strategy
- SEO assets compound over 6–18 months and require no ongoing effort

**4. Real estate agent subscriptions ($99/mo) — at scale**
- Buyer's agents working with relocating clients represent a large share of their business
- Co-branded tool to send prospects through → drives warmer leads to agents
- Target: high-inbound markets (Carolinas, Tennessee, Texas, Florida, Idaho)

**5. API / data licensing — longer horizon**
- Scoring dataset licensable to: moving company apps, HR relocation software (Relocity, CartaHR), mortgage platforms
- Requires 12+ months of usage data to demonstrate value

### Revenue Projections (conservative)

| Timeline | Model | Monthly Revenue |
|---|---|---|
| 6 months | Reports + affiliate CTAs | $500–$2K |
| 12 months | + basic SEO traction | $1K–$5K |
| 24–36 months | + agent subscriptions + SEO compounding | $10K–$30K |

*Nomad List benchmark: bootstrapped to $33K/month before reaching scale, $5.3M ARR after 12 years, solo founder throughout.*

---

## Growth Strategy

### Immediate (Month 1–3)
- **ProductHunt launch**: AI-powered city recommendation is a strong hook for tech-forward early adopters. Target: top 5 for the day → 500–2,000 signups, newsletter pickup
- **Reddit**: Authentic participation on r/SameGrassButGreener, r/personalfinance, r/digitalnomad, r/financialindependence. These communities are Touchgrass's exact audience and have high organic conversion
- **Shareable results**: Make the ranked output into a social card ("I asked an AI where to move and it said #1 Raleigh — here's why"). Curiosity gap drives referrals.

### Medium-term (Month 3–12)
- **Programmatic SEO**: Build city pages, comparison pages, persona-based list pages. 6–18 month compounding payoff
- **Content marketing**: Annual "Where Americans Are Moving" report using aggregate conversation data. Linkable asset for local newspapers, HireAHelper, moveBuddha

### At Scale (12M+ visitors)
- **Zillow/Premier Agent**: Referral partnership for relocating homebuyers becomes viable with proven traffic volume
- **City economic development offices**: Sponsorship/branded content ($5K–$50K/city/year, as Livability.com does)
- **Enterprise/HR white-label**: Corporate relocation packages, 64% of employees declined relocation in 2023 — companies are looking for tools to improve acceptance rates

---

## Why Now

1. **AI-native timing**: LLMs make conversational preference derivation trivially buildable. Two years ago this required a complex form + rule-based scoring. The moat is being first to market with a polished product, not the AI itself.

2. **Post-COVID migration normalization**: Remote work decoupled housing from employment for tens of millions of Americans. The question "where should I live?" is now a real choice for more people than at any point in US history.

3. **Climate migration accelerating**: +121% YoY growth in climate-motivated moves. Flood zones, wildfire risk, extreme heat are becoming primary filters. Legacy tools don't model this well; Touchgrass can.

4. **No incumbent has shipped AI**: bestplaces, numbeo, areavibes are all 10+ year old data-table products with no AI roadmap. They are slow to ship. The window is open.

---

## Team

*Solo technical founder. ~100 hours invested to working product. Full stack: FastAPI, PostgreSQL/PostGIS, Claude API, Docker.*

---

## Ask / Use of Funds

*[To be completed for investor conversations]*

---

*Data sources: HireAHelper 2024 Migration Report, moveBuddha Moving Statistics 2025, Coherent Market Insights Corporate Relocation 2025, GetLatka Nomad List revenue data, Similarweb/SEMrush competitor traffic estimates, Placer.ai Domestic Migration 2025, St. Louis Fed WFH Migration research, Atlas 2024 Corporate Relocation Survey.*

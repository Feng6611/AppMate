# ASO Metadata Optimization — Detailed Compendium (Title / Subtitle / Keywords / Description)

> Source files:
> - [EN] *The Advanced App Store Optimization e-Book* — EN — 2022 (AppTweak/Phiture)
> - [CN] *Mastering Apple's Traffic Ecosystem: Unlocking the New Code of App Traffic* — Shi Jiangang (Publishing House of Electronics Industry, 2021)
>
> This document systematically organizes everything from the two ASO books above that directly relates to optimizing **title, subtitle, keywords, and description**, preserving the original data, cases, operational details, and methodology frameworks as far as possible, presented in a table-of-contents structure. Section numbers (§1–§12 and their sub-sections like §10.1, §7.3) are referenced by number throughout the `aso-optimize` skill.

---

## Table of Contents

**§1. Overall frameworks**
- 1.1 The ASO value model (CN book)
- 1.2 The ASO Stack framework (EN book)
- 1.3 The definition of modern ASO

**§2. Search algorithm and indexing mechanism**
- 2.1 The 3 elements of the search algorithm: eligibility, relevance, ranking strength
- 2.2 The indexing mechanism in detail
- 2.3 "Free" ranking keywords on the App Store
- 2.4 Plural and compound word ranking issues
- 2.5 New-app week-long keyword boost

**§3. Keyword ranking signals**
- 3.1 Primary ranking signals (downloads, ratings & reviews, keyword conversion rate, retention rate)
- 3.2 Other possible ranking factors

**§4. The Keyword Optimization (KWO) Cycle**
- 4.1 Step 1: Keyword research
- 4.2 Step 2: Keyword prioritization
- 4.3 Step 3: Targeting keywords in metadata
- 4.4 Step 4: Measuring keyword performance

**§5. Title (App Name) optimization**
- 5.1 Character limits and historical changes
- 5.2 The weight of the title
- 5.3 Naming strategy and brand/keyword balance
- 5.4 Google Play policy guideline changes
- 5.5 The title from a conversion-rate-optimization (CRO) perspective

**§6. Subtitle optimization**
- 6.1 App Store subtitle rules and weight
- 6.2 Two core subtitle recommendations

**§7. Keyword field optimization — App Store only**
- 7.1 Keyword field basic rules
- 7.2 How Apple uses the keyword field for indexing
- 7.3 iOS keyword field best practices (full checklist)

**§8. Description optimization**
- 8.1 Google Play short description
- 8.2 Google Play long description and optimization techniques
- 8.3 The special status of the App Store description

**§9. Other metadata optimization**
- 9.1 Developer name / seller name
- 9.2 In-app purchase names (IAP names)
- 9.3 In-app event names
- 9.4 Package name — Google Play
- 9.5 Visual word recognition

**§10. The "three layers of skill" in keyword coverage (CN book's distinctive methodology)**
- 10.1 Layer 1: shallow rules (explicit rules) — basic elements and word selection
- 10.2 Layer 2: deep rules — hidden positions and localization
- 10.3 Layer 3: meta-rules — Chinese word segmentation and indexing sources
- 10.4 Practical word-splitting and word-grouping cases
- 10.5 The power of time — accumulating high-weight keywords

**§11. ASA data feeding back into keyword optimization (CN book)**

**§12. Conversion value (Value_Rate) — creative-asset and copy optimization methodology (CN book)**

---

## §1. Overall frameworks

### 1.1 The ASO value model (CN book, Ch. 4 §1)

The CN book proposes a concise ASO value formula:

```
Value_ASO = Value_Traffic × Value_Rate
```

`Value_Traffic` is the traffic-exposure value brought by keyword coverage; `Value_Rate` is the user-conversion value brought by creative-asset optimization. The two are multiplicative, not additive — if exposure doubles and conversion doubles, the final effect is 4×, not 2×.

`Value_Traffic` in concrete terms: through optimizing keyword selection, splitting, and grouping in the iTunes Connect Keyword settings, covering more words in search and achieving higher search rankings, so the product gets more exposure opportunities.

`Value_Rate` in concrete terms: through improving title, icon, description, screenshots, and other assets, getting more user attention, a higher click-through conversion, and a higher download conversion.

Basic ASO optimization has two quantifiable goals: more keyword coverage, and higher ranking — and more keyword coverage is the top priority. In practice, coverage results vary enormously between optimizers — for the same app, one optimizer might cover a few hundred keywords while another covers tens of thousands. With the same 100-byte keyword entry space, some people cover only 100 keywords, some cover 1,000, and some cover more than 10,000.

Many factors are involved; one very important factor is whether you have fully internalized Apple's rules. Understanding and mastering Apple's rules can be divided, from shallow to deep, into three levels of insight: shallow rules, deep rules, meta-rules. The three levels of understanding lead to three different ways of operating and three different coverage results.

### 1.2 The ASO Stack framework (EN book, Ch. 1)

The EN book uses the ASO Stack framework developed by Phiture, dividing ASO into two pillars:

- **Visibility**: keyword optimization (KWO), getting editorial featurings, top charts, store ads.
- **Conversion**: creative-asset optimization (icon, screenshots, video, copy), ratings & reviews, localization.

The ASO Stack is a one-page ASO understanding-and-strategy cheat sheet, useful for both beginners and experienced practitioners. The book focuses on two main ASO goals: visibility and conversion. Visibility covers everything from keyword optimization to in-app events (iOS 15) and browse traffic; conversion covers everything that helps improve download conversion, from creative-asset optimization to ratings & reviews and localization.

### 1.3 The definition of modern ASO (EN book, Ch. 1)

The EN book notes that ASO was once simply defined as "SEO for apps" — optimizing metadata to gain maximum visibility in app store search results. But as app stores have changed over the years and more resources have been invested, this definition is no longer sufficient.

The definition of modern ASO is broader: it aims not only to optimize an app's visibility across all available placements within the store, but also to optimize the app's appeal to users, converting browsing into downloads. In practice, ASO ranges from optimizing textual and visual metadata, to strategies that encourage users to leave positive ratings and reviews, and also includes other work such as increasing visibility through store featurings.

---

## §2. Search algorithm and indexing mechanism

### 2.1 The 3 elements of the search algorithm (EN book, Ch. 2)

Understanding the app store search ranking algorithm requires considering three core questions:

1. **Eligibility**: Is your app eligible to rank for a given keyword? This usually requires specifying that keyword in the app's metadata. The store indexes apps based on the keywords the developer includes in metadata (title, subtitle, short description, keyword field, etc.). This is the first core factor affecting the search algorithm.
2. **Relevance**: How relevant is a given keyword to your app? While influenced by "secret sauce" factors, this is mainly defined by the keyword's position in metadata.
3. **Ranking Strength**: How much ranking power does your app have for that keyword? Defined by factors outside metadata, such as install conversion rate and keyword retention rate.

Notably, it is also possible to rank for a word without specifying it in metadata: Google's algorithm uses machine learning (including skip-gram and other embedding neural-network models) to determine relationships between keywords (synonyms, similar contexts, typos/slang, etc.). The algorithm matches similar words and then "guesses" the intent behind the search. This means that if a search keyword is algorithmically associated with another keyword in the app's metadata, the app can rank for that search term even if the keyword itself is not in metadata.

Apple's algorithm is simpler than Google's, but it also allows apps to rank for some keywords that do not need to be specified in metadata.

### 2.2 The indexing mechanism in detail

**[EN book perspective]**
The app store shows apps in search results based on the keywords a developer includes in metadata (title, subtitle, short description, keyword field, etc.). Like SEO, the store considers the keywords in metadata to try to match the app to the user's search query. It is therefore important to include relevant keywords in these fields based on user search behavior.

**[CN book perspective — ASO keyword indexing sources (Ch. 4 §4)]**
The CN book gives a deep low-level analysis of Apple's indexing mechanism:

If a user searches "游戏" (games) on the App Store, does Apple need to scan the info of all 2 million apps on the platform? Obviously not — Apple relies on an index.

An index is like a book's table of contents. Apple builds an index for every keyword that appears in each app, recording: how many apps the keyword appears in, which apps they are, how many times it appears in each app, and exactly where (name, subtitle, keywords, developer name, IAP info). So when a user searches that keyword, Apple just finds the corresponding index entry to return precise results.

**Positions Apple indexes:**
- App name
- Subtitle
- Keyword field
- Developer name
- In-app purchase info (IAP)

**Content Apple does NOT index:**
- App description
- User reviews

Building the index is a systems job: first filter, classify, and filter app info, ignoring various non-text symbols, extracting valid text content; then apply natural language processing (NLP) to the text — for example, the China App Store needs a Chinese word-segmentation algorithm to split long text (name, subtitle, keywords) into individual keywords.

### 2.3 "Free" ranking keywords on the App Store (EN book, Ch. 2)

The EN book found that on the App Store, apps can be indexed and ranked for the following keywords without specifying them in metadata — these are called "free keywords":
- App category names (e.g. "Health & Fitness")
- Common stop words (the / a / by, etc.)
- Other words automatically associated by Apple's system

This means you do not need to waste precious 100-character keyword-field space adding these words.

### 2.4 Plural and compound word ranking issues (EN book, Ch. 2)

Apple does not always correctly match a singular keyword to its plural or compound form. Although Apple's algorithm is improving at matching plural/singular, the process is far from perfect on the App Store, especially for non-English searches.

**How to judge**: use an ASO tool to analyze the singular and plural variants of the same word (e.g. "fox" and "foxes") and compound words (e.g. "audiobooks" and "audio books"):
- If one variant's ranking is very close to the root word (difference under 15%), Apple has probably auto-matched the variants and you only need to specify one form. For example, "audiobooks" / "audio books" (compound) and "podcast" / "podcasts" (plural) rank closely.
- But if the difference is large — e.g. "mouse" and "mice" — Apple is highly unlikely to auto-match, and you need to add both forms in metadata.
- If a search term is one of your primary keywords and both variants have substantial search volume (e.g. "podcast" = 68, "podcasts" = 49), it is recommended to target both singular and plural in metadata.

The safest default is to add both forms, then determine through testing in later metadata iterations whether the plural can be safely removed.

### 2.5 New-app week-long keyword boost (EN book, Ch. 2)

**iOS only**: the first week after a new app launches is the only window in which Apple artificially boosts an app's visibility.

Because Apple cannot judge how good a brand-new app is or how relevant its metadata keywords are, in order for the algorithm to measure metrics like retention and conversion from different search terms, during the first week (7 days) after launch Apple artificially places the app in a higher search position for the keywords provided in its metadata.

Two strategies for using this first-week boost window:
- **Strategy 1**: target some loosely-relevant but extremely high search-volume keywords, hoping to capture more downloads.
- **Strategy 2**: ensure the app covers its most relevant keywords from the start, so those keywords' performance history starts high, giving the app a better chance of holding a high ranking after the first-week boost ends.

---

## §3. Keyword ranking signals

### 3.1 Primary ranking signals (EN book, Ch. 2)

The EN book systematically lists the main factors the ASO community has identified as influencing Apple's and Google's keyword ranking algorithms:

1. **App downloads (Apple & Google)** — Downloads are the strongest ranking signal on both platforms, especially downloads from the keyword in question. Download velocity is a major attribute within total downloads. Downloads matter especially on the App Store. For example, if a high-download music app adds the keyword "audiobooks" to its title, it may rank well on the strength of its large overall download volume alone. Because stores tend to rank high-download apps for high-search-volume keywords, small developers should first focus on long-tail or low-search-volume, low-competition keywords.
2. **Ratings and reviews (Apple & Google)** — Star rating and the growth rate of reviews/ratings are important factors in the ranking algorithm. Both Apple and Google have officially stated that star rating, user reviews, and review count are considered when ranking apps. Recent Phiture research found no direct correlation between App Store ratings and keyword ranking, but indirectly, the higher conversion rate from a higher rating may raise rankings over time.
3. **Keyword conversion rate (Apple & Google)** — A leading indicator of whether an app can rank is the historical proportion at which the app converts that keyword's searches into installs. Both Apple and Google want to show apps more likely to be downloaded.
4. **Keyword retention rate (especially important for Google)** — Google's keyword ranking algorithm has gradually shifted from relying on downloads and download velocity toward weighting user retention more heavily. In late 2016/early 2017, the Google Android team announced that user retention is a more important keyword-ranking signal than downloads. If an app's retention is low, driving more downloads becomes a negative signal, causing the app's ranking for that keyword to gradually fall — because a lot of downloads paired with low retention is enough to indicate the app is not worth showing to future visitors using that keyword.

### 3.2 Other possible ranking factors (EN book, Ch. 2)

Other possible (not fully confirmed) ranking factors proposed by the industry:

- **User engagement and app indexing** — iOS apps can be indexed in Apple Spotlight search; Android apps can be indexed on google.com. Setting up app indexing may be a positive ranking signal.
- **Localization** — From a UX perspective it is reasonable to rank localized apps ahead of non-localized ones (though unconfirmed).
- **Video assets** — The presence of a high-quality preview video may be used as a favorable signal for keyword ranking.
- **Average app session length or number of launches** — As a deeper user-engagement factor, may influence keyword ranking.
- **Average revenue per user (ARPU)** — Apple and Google earn revenue from paid downloads and in-app purchases, so they may reasonably favor apps with higher per-user revenue in keyword ranking.
- **Short vs. long description weight changes (Google Play)** — A few years ago the short description was considered more impactful for ranking; but the evolution of the Google Play algorithm leads ASO experts to now believe the long description carries more weight if keywords are repeated multiple times in it.
- **Text on screenshots / screenshot filenames** — The hypothesis that Google recognizes text on assets and indexes the app has been disproven. Tests that changed a screenshot filename from "IMG0001.png" to "new-keywords-to-rank-for.png" also failed to improve rankings.
- **Whether reviews are indexed** — There is no definitive evidence that reviews are indexed on the App Store, but there have been cases where "keyword-stuffing" black-hat reviews coincided with ranking increases.
- **Ranking independence across countries** — Downloads in one country do not affect keyword or chart rankings in another. For example, even if an app has 1 million installs on the "chat" keyword in the UK, it will not automatically rank higher in the US or Canada. However, some apps' localized keyword fields can influence their ranking relevance in other countries.

---

## §4. The Keyword Optimization (KWO) Cycle

Based on Phiture's "Keyword Optimization Cycle" framework, the EN book defines four stages of keyword optimization. The KWO process is iterative — continuously adjusting the app's metadata is the key to success.

### 4.1 Step 1: Keyword research

Before you start attracting users, you need to create a large keyword list (the keyword backlog). These should be words that people could reasonably be expected to use to find your app.

The initial step is to create a fresh keyword backlog of generic search terms. You do not necessarily need to include your own app name or competitors' app names in the list — you will naturally add your own app name in metadata, and an app usually ranks #1 for its own name (if the name is unique).

On both the App Store and Google Play, adding a competitor's app name in metadata is prohibited. So exclude those names from research — unless the competitor's brand name is itself a generic search term (like "calm" or "booking").

**Keyword research sources and methods:**
- **(a) Brainstorming** — Start from common sense: how would you search for your own app? Think about the app's main features and benefits; check your website keywords; ask colleagues to list keywords they would use to find your app. The most effective team brainstorm has each person independently come up with as many keywords as possible.
- **(b) Competitor keyword analysis** — Analyze competitors' titles, subtitles, long/short descriptions, and screenshot copy. On Google Play you can directly see a competitor's full metadata; on the App Store it is harder because App Store Connect hides the 100-character keyword field. Use ASO tools to "peek at" the keywords competitors use. Tip: to test whether an iOS app ranks for a keyword, search the brand name plus the word — e.g. search "Spotify streaming" to judge whether Spotify ranks for "streaming".
- **(c) App Store autofill**
- **(d) Google Keyword Planner tool**
- **(e) Shuffle keyword combinations**
- **(f) Vocabulary from user reviews**
- **(g) Apple Search Ads search terms**

You can use Excel or an ASO tool to build the keyword backlog. With Excel you can use a single column, or expand to multiple columns annotating the source.

### 4.2 Step 2: Keyword prioritization

From the keyword backlog, filter out 10 to 20 "starred keywords" — the words most valuable in search volume and relevance, which will play a key role in the app's visibility.

**Ranking basis**: search volume, relevance, competition difficulty, conversion potential.

If you do not have an MMP (mobile measurement partner), consider Apple-provided metrics: search-term-level tap-through rate (TTR) and conversion rate (CR) are good indicators of a specific keyword's relevance.

### 4.3 Step 3: Targeting keywords in metadata

This is the core step of keyword optimization; see §5–§9 below for the detailed breakdown.

**Core principle**: the more visible the metadata, the greater its weight. Weight ranking:
- App Store: Title > Subtitle > Keyword field
- Google Play: Title > Short description > Long description

You need to effectively target keywords in the following metadata positions: title, the 100-character keyword field (App Store), short description, long description, developer name, in-app purchases, and package name.

### 4.4 Step 4: Measuring keyword performance

Based on data, you can filter out 10 to 20 starred keywords — beyond the app name and competitor names — that bring meaningful traffic to the app. These keywords are crucial to the app's in-store visibility. Continuous optimization is the core of ASO.

---

## §5. Title (App Name) optimization

### 5.1 Character limits and historical changes (EN book, Ch. 1 & 2)

App titles on both the App Store and Google Play are currently limited to a maximum of 30 characters.

**Historical changes:**
- The early App Store allowed 255-character titles. Developers who exploited this huge space for keyword optimization could achieve extremely long, extremely user-unfriendly titles.
- 2016: Apple reduced the title to 50 characters.
- 2017: Apple further reduced it to 30 characters; at the same time introduced the 30-character subtitle (iOS 11).
- Google Play: limited the title to 30 characters → increased to 50 in 2017 → reverted to 30 again in 2021.

### 5.2 The weight of the title (EN book, Ch. 2)

Both Google Play's and the App Store's search algorithms treat the app title as the highest-weight metadata element. Therefore, including a keyword in the app title gives you the highest chance of achieving a meaningful ranking for that keyword.

Store guidelines require app titles to be unique, recognizable, and to explain what the app does. The app name should not be misleading and should avoid words referencing app performance like "best", "#1", "leading".

For the "starred" high-search-volume, high-relevance keywords mentioned in the prioritization step, one well-placed keyword (or keyword combination) can significantly boost your visibility. Use exact keyword placement where possible — this helps search-term conversion and helps the app rank better in search results.

**Metadata weight ranking (high to low):**
- The more visible the metadata (title outweighs the iOS keyword field).
- The fewer characters a metadata element allows (more limited space = greater weight).
- The frequency a keyword appears across all metadata (Google only).
- Exact match gets higher relevance weight than fuzzy match.

### 5.3 Naming strategy and brand/keyword balance (EN book, Ch. 2)

Most large brands use a similar approach when naming apps — balancing brand recognition and keyword optimization.

Because title character space is limited, publishers are finding creative ways to fold generic keywords into the app name to ensure they rank high for the most valuable keywords. Some examples:
- `Meditation for Sleep and Calm | Down Dog`
- `Dating, Meet Curvy Singles. Match & Date @ Wooplus`

Some developers completely drop the brand name to maximize available character space for keywords. But for apps with a strong brand this is usually a bad idea — you might lose brand recognition, even lose the #1 position for brand searches.

For example, even a strong brand like STARZ should understand that not all store visitors know the brand. Changing the title to `STARZ - Movies & TV Shows` not only helps visibility but also helps conversion.

For new apps without brand awareness, creating an app name that includes keywords related to the app's function (like "editor", "reader", "tracker") is a simple way to help the app rank high for the most valuable keywords. Some apps even put a generic keyword before the actual app name.

**Space-saving techniques:**
- Target only the word root (e.g. "run" instead of "running").
- Omit commas.
- Use a colon (:) instead of the traditional dash (–) to separate app name and tagline.
- Use the `&` symbol instead of "and".

The 30-character limit is often very constraining and can lead to fewer descriptive words for apps with long brand names — e.g. `Adobe Acrobat Reader` leaves room for only two extra keywords after the brand name.

**"Roadblocking" strategy (EN book, Ch. 2)**: developers with multiple apps can use a "roadblocking" strategy — having multiple apps target the same set of keywords, trying to "occupy" the top search results and push competitors down. This is especially common when a developer tries to "protect" a popular brand name.

**Brand-attack strategy**: if a competitor's name contains a generic keyword (like "Booking" or "Weather"), targeting those keywords in your own metadata is a low-risk way to capture a share of users searching for that competitor. Also consider using Apple Search Ads for brand defense and attack strategies.

### 5.4 Google Play policy guideline changes (EN book, Ch. 2)

In April 2021, Google announced major policy changes for app metadata and new creative-asset guidelines:
- App name shortened from 50 characters to 30 characters (the most significant change).
- Keywords implying app store performance ("top", "best", "#1") are prohibited in the title, icon, and developer name.
- Calls-to-action that incentivize installs ("download now", "install now", "play now", "try now") are restricted in the title or icon.
- Promoting offers via keywords (like "free") is prohibited.
- Emoji/emoticons, repeated punctuation, and all-caps are no longer allowed.
- Avoid easily-outdated time-limited taglines or callouts.

### 5.5 The title from a CRO perspective (EN book, Ch. 3)

Although 99% of the time the title is used mainly for keyword optimization, you can also experiment to judge whether a keyword-optimized title also improves conversion.

Adding keywords to the title is beneficial not only for visibility but is also, to a large extent, a positive conversion-rate-optimization move — it quickly and effectively communicates the app's value proposition. But a keyword-stuffed title can lower conversion, which in turn lowers keyword ranking.

Optimizing textual metadata tends to have a smaller impact on conversion (per Storemaven research, optimizing the app name brings an average 8% CVR lift; per another study, 14.4% for the App Store and 14.5% for Google Play). The industry has observed ASO strategy increasingly focusing on visual creative-asset optimization to lift conversion, while metadata optimization is more aimed at increasing traffic. But this does not mean textual metadata can be ignored — a complete CRO strategy should ultimately cover all aspects of the app page.

On Google Play, the title matters more for conversion (because the title is more prominent in search results).

---

## §6. Subtitle optimization

### 6.1 App Store subtitle rules and weight (EN book, Ch. 2)

Apple allows developers to add a subtitle next to the title, up to 30 characters, shown below the title both in search results and on the App Store product page.

Following the "the more visible the metadata, the greater its weight" rule, the subtitle's weight appears to be higher than the iOS keyword field but lower than the title.

Consult your "starred keyword" list and consider adding keywords that score high in both search volume and relevance and that describe the app's main features or benefits.

The CN book confirms: the subtitle is 30 characters long, fitting up to 30 Chinese characters.

### 6.2 Two core subtitle recommendations (EN book, Ch. 2)

1. Do not repeat keywords already in the title in the subtitle — repetition does not add weight and wastes precious space.
2. Avoid overly generic phrases like "most popular game" or "social networking".

The CN book adds: when using localized language settings, keep the English (UK) version's name, subtitle, and the Simplified Chinese version consistent; aim for conciseness, do not stuff, and never include competitor vocabulary.

---

## §7. Keyword field optimization — App Store only

### 7.1 Keyword field basic rules (EN book, Ch. 2)

In App Store Connect you can provide a keyword list (keyword field) for each chosen localization. This keyword field is invisible to users, hidden off the app product page, and helps the App Store algorithm further understand what your app is and which keywords it should rank for.

The keyword field is at most 100 characters, so it is very important to carefully follow best practices to maximize available space.

The CN book confirms: keywords are 100 characters long, fitting up to 100 Chinese characters.

### 7.2 How Apple uses the keyword field for indexing (EN book, Ch. 2)

Before adding keywords to the keyword field, it is important to understand how Apple uses these keywords to index the app: Apple combines all keywords across the keyword field, title, and subtitle to rank the app for long-tail combinations.

When choosing keywords for the 100-character keyword field, pick keywords from the top of the priority list, and also consider the keywords with the most potential to generate large numbers of long-tail combinations.

### 7.3 iOS keyword field best practices (full checklist) (EN book, Ch. 2)

1. Separate keywords with commas, not spaces.
2. Do not repeat keywords in the keyword field. Repeating a keyword does not raise its ranking and wastes space.
3. Do not repeat keywords already in the title or subtitle. Adding a keyword to both the keyword field and the title/subtitle does not give extra weight.
4. Order does not affect weight. A keyword at the end of the keyword field is as important as one at the start.
5. Split phrases or long-tail keywords into individual words. For example, add `photo,filter` instead of `photo filter`, because Apple automatically combines all words in the app's metadata. Adding `photo,filter` has the same ranking opportunity as `photo filter`.
6. Try to add only singular forms: Apple recommends including only singular keywords in the keyword field. But as noted, Apple does not always correctly match plural and singular keywords, especially in foreign languages.
7. Avoid "free" words: stop words (the/a/by, etc.), words derivable from the category (like "Health & Fitness"), or other "free words" do not need to be added to App Store metadata to be eligible to rank.
8. Less is less: not using all 100 characters in the hope of giving the included keywords more weight is a bad idea. You do not improve some keywords' ranking by removing others. Use all 100 characters!
9. After adding the title/subtitle keywords, go back to the keyword backlog, skip the already-added keywords, and start adding the next-highest-priority words to the keyword field.

---

## §8. Description optimization

### 8.1 Google Play short description (EN book, Ch. 2)

Google Play's short description is limited to 80 characters, giving marketers more flexibility than the App Store to communicate the app's value proposition. Keywords used in the short description are indexed by the algorithm, but over time their impact on ranking has been observed to be smaller than keywords in the title or high-density keywords in the long description.

To maximize the short description's impact on keyword ranking, try (where possible) to repeat the most valuable keywords from the title in the short description. Unlike Apple, Google considers keyword density.

### 8.2 Google Play long description and optimization techniques (EN book, Ch. 2)

The long description can hold up to 4,000 characters and is indexed by Google Play. But filling all 4,000 characters does not necessarily give you a ranking advantage. In fact, keyword density matters more to the Play Store algorithm than the absolute number of keyword repetitions.

Example: repeating the keyword "music" 100 times in a 4,000-character description is worse than repeating "music" 5 times in a 300-character description — the latter has higher keyword density and greater weight.

Although the 4,000-character space is large, the long description is not very prominent on the Google Play app page. But it does represent an opportunity to promote the app and highlight key differentiators.

**Techniques for optimizing the long description:**
- **(a)** Organize the content into readable paragraphs with clear subheadings. Make it easier for store visitors to scan and find the information most relevant to them.
- **(b)** Make the first few lines the most valuable. Few users scroll all the way to the bottom of a long description. Make sure to grab attention and convey the main message within the first 3 lines.
- **(c)** Similarly, to maximize the long description's keyword impact, try to include the most valuable keywords in the first few lines. Google assigns higher weight to keywords used in the first few lines — e.g. mentioning "restaurant" 5 times in the first few sentences works better than the same number of times scattered throughout the description.
- **(d)** Include media coverage mentioned, awards won, and influential reviews. But follow store guidelines and avoid including unattributed anonymous reviews.

There are free tools that help calculate the density of the highest-priority keywords in the long description (e.g. AppTweak's free Keyword Density Counter).

### 8.3 The special status of the App Store description (EN book & CN book)

The EN book explicitly notes: although the App Store also has a long description, it is not indexed by the App Store search algorithm. That is, the App Store description has no direct effect on search ranking.

But the EN book also notes it is still worth applying some keyword-optimization logic to the App Store description, because the description is indexed on the web (web SEO effect).

The CN book likewise confirms: "app description" and "review" info are not indexed by Apple. The description's main role is user-facing conversion, not search ranking.

The CN book further emphasizes in Ch. 5: in ASO practice, companies currently emphasize `Value_Traffic` (keyword coverage and traffic acquisition) and neglect `Value_Rate` (ASO copy and creative-asset production). Conversion-rate optimization lacks quantitative means, and even when effective is not easily tied to KPIs.

---

## §9. Other metadata optimization

### 9.1 Developer name / seller name (EN book & CN book)

**[EN book]**
The developer name (Google Play) or seller name (App Store) is indexed on both platforms to target keywords, especially on Google Play. For example, Booking.com's developer name is visible in Google Play search results.

On Google Play you can update the developer name anytime in account settings. On the App Store it is more complex because the developer name is tied to the D-U-N-S number — you need to choose the right name at developer registration.

The developer name is not visible in search results but is indexed — even if a brand name (like "Microsoft" or "Adobe") is not in the app title, the app still ranks for those brand keywords.

**[CN book (Ch. 4 §3)]**
The developer name is also indexed by Apple. Some developers, after discovering this rule, changed the developer name into a long string of keyword groups, but were later penalized by Apple.

An individual developer name is fixed at account application and cannot be changed. A company developer account can be changed — using a Chinese company name, especially when the app name and the company brand differ, lets the Chinese company developer name directly help the app cover the company brand. Developers who need to change it can email Apple.

The weight of a developer account is implicitly judged by Apple across multiple dimensions — product weight, product traffic, number of apps under the account, contributed revenue — giving low/medium/high keyword coverage results.

### 9.2 In-app purchase names (IAP names) — App Store (EN book & CN book)

**[EN book]**
In-app purchases (IAPs) also appear in App Store search results and are indexed for the keywords used in the IAP title. IAPs usually appear in search results alongside their supporting app, which shows that IAPs do provide extra keyword space to increase an app's visibility.

For example, the language-learning app Babbel: its title, subtitle, and keyword field space were not enough to cover all supported languages. It targeted "learn spanish" and "learn french" (rank #2) in the subtitle, and also ranked #2 for "learn russian" — which is exactly the title of one of its IAPs.

**[CN book (Ch. 4 §3)]**
Subscription items often appear in App Store search results. You can set up to 20 IAPs and subscription items, each with a name, description, and icon.

- Case 1: when searching "股票" (stocks) and "炒股" (stock trading), the subscriptions of 同花顺, 腾讯自选股, and 东方财富 all appear in the ranking results. When searching 同花顺 and 东方财富, the IAP item ranks #2 — regardless of conversion, this is very favorable for brand protection: it protects your brand's keyword traffic, leaving competitors little room under that keyword.
- Case 2: in the search results for the industry word "英语" (English) and the brand word "爱奇艺", the subscription ranks right behind the main app — very helpful for both brand protection and improving monetization efficiency.

### 9.3 In-app event names — App Store (EN book)

Like IAPs, in-app events' event names and short descriptions are also indexed, giving developers another opportunity to increase visibility.

The event name is at most 30 characters. Choose a unique, descriptive name. Avoid generic terms like "game event" or "major update", and claims like "best" or "#1". Apple also recommends not using the title to explain the event type (like "film premiere" or "challenge"), because the event badge already shows that information.

The event short description is at most 50 characters, used to briefly explain the event content.

### 9.4 Package name — Google Play (EN book)

The Bundle ID on the App Store cannot be used for ranking. But on Google Play, the unique package name you choose for the app can influence ranking.

Case: searching "zara" on Google Play showed Super Mario Run ranked #11, even though Nintendo did not mention "zara" in its metadata. It turned out Nintendo used "zara" in the package name.

Although the package name's influence has weakened compared to a few years ago (Mario Run's rank for "zara" has now dropped to #150), many apps and games still use this strategy to repeat the most relevant keywords in the package name.

Recommended naming convention: `com.brand.title.keyword1.keyword2`

Note: although you can change the package name in `AndroidManifest.xml`, Google Play treats your app as a brand-new listing and you lose all history (reviews, downloads, etc.). So carefully decide which keywords to target before launch.

### 9.5 Visual word recognition (EN book, Ch. 2)

Visual word recognition refers to a user's ability to recognize relevant visual words in app listing elements (like the title or screenshot copy). If a user searches "learn spanish" and sees visual cues highlighting that the app offers what they searched for, they are more likely to convert.

If an app cannot convert an impression from a keyword search into a real user, that keyword's ranking score falls.

**Strategies to optimize visual word recognition:**
- Include the search term in visible metadata elements (title, subtitle, screenshots, or video).
- Creatively present the user intent behind the search term (e.g. weight-loss imagery for the keyword "diet").
- Out-position competitors on that search term.

Case: after iOS 14 introduced Widgets, search volume for the keyword "widget" spiked. Among top weather apps, The Weather Channel was the only one to add the keyword "widget" to visible metadata (the subtitle) and screenshots, and therefore ranked highest for that keyword.

---

## §10. The "three layers of skill" in keyword coverage (CN book, Ch. 4 — distinctive methodology)

This is the CN book's most central methodology, dividing the understanding of Apple's keyword rules into three progressive levels of insight.

### 10.1 Layer 1: shallow rules (explicit rules) — basic elements and word selection

"Shallow" means "on the surface" — the literal rules. At this layer, you can read Apple's literal rules and operate and configure accordingly.

**The three basic elements of keyword coverage:**
1. App name: 30 characters long, up to 30 Chinese characters.
2. Title/subtitle: 30 characters long, up to 30 Chinese characters.
3. Keywords: 100 characters long, up to 100 Chinese characters.

**The two dimensions of word selection:**
- Relevance: how related the keyword is to the product.
- Traffic size: called the search index or "heat" (popularity) in Apple's system.

By relevance: brand words, competitor words, industry words.
By search index: high-heat words, medium-heat words, low-heat words.
Priority by relevance: **brand words > industry words > competitor words**.

**Four-quadrant analysis:**
- Tier 1: high relevance + high heat
- Tier 2: high relevance + low heat
- Tier 3: low relevance + low heat
- Tier 4: low relevance + high heat

**Brand words in detail:**
The app name basically covers the main brand words, but consider these cases:
- Homophones/typos: e.g. 小米有品's "小米优品" / "优品"; 罗辑思维's "逻辑思维" — sometimes these words have non-trivial search heat.
- Multi-brand: e.g. 美团 contains multiple brand words like 外卖 (delivery), 骑手 (rider), 打车 (ride-hailing), and the typo "每团".

**Industry words in detail:**
Basically composed of multiple groups of "core word + business-association word or generic suffix word", forming a tree structure. Industry words are not only rich in composition but are also the decisive factor in keyword competition.

Industry-word expansion method (example: "汽车" / cars): starting from the core industry word, expand from four angles:
1. **Common words**: 汽车大全, 汽车宝典, 汽车头条, 汽车测评 (association words)
2. **Media-related words**
3. **Transaction-related words**
4. **Software-platform-related words**: 汽车平台, 汽车软件 (generic suffix words / generic words)

If there are too many keywords, use search heat as a filter — e.g. keep only words with a search index above 4605, or a popularity above 50.

**Competitor words in detail:**
Mainly the process of defining and finding competitor apps. Advantages: larger traffic, fewer competitors. Disadvantages: hard to optimize to #1, and low conversion rate. Years ago, 喜马拉雅 optimized a competitor word to the #1 position. Tip: search the target app's recent industry reports (especially for traditional industries) — you may find competitor words that have a search index but no competition. With the development of ASA, there are also new methods via competitor bid words, Apple-recommended related apps, ASA recommended words, etc.

**Word-selection priority:**
- Brand words are Tier 1 or Tier 2 — prioritized for inclusion.
- Industry words are organized as logical word strings of "core + association word + generic word", filtered by quadrant.
- Competitor words are usually Tier 3.

**Result**: for a new app, following the logic and steps above, the keyword coverage count can easily break a thousand.

### 10.2 Layer 2: deep rules — hidden positions and localization

The focus of the second layer of skill is to fully internalize the rules beyond the literal rules, especially the App Store's implicit rules. These rules are not written in Apple's official docs, are hidden deeper, and are tacit knowledge.

Beyond the three explicit elements of the shallow rules, there are hidden positions and methods that can affect keyword coverage — and even increase the relevance between a keyword and the app, ultimately affecting search ranking:

**(1) Localized language settings — doubling keyword capacity**

Through localized language settings, you can add another 100 characters of keyword entry, taking keyword capacity from 100 characters to 200 characters.

Principle: each language version of the App Store can have a 100-byte keyword field. Setting up two versions — the primary language and a localized language — is equivalent to having 200 bytes.

Taking mainland China as an example: it supports two localized language versions — Simplified Chinese and English (UK). By setting up two different Chinese keyword schemes, you can dramatically increase keyword coverage.

On whether setting Chinese on the English (UK) version passes review: per practical experience, Apple reviews the app name and title strictly but reviews keyword settings loosely. So it is recommended to keep the English (UK) version's name and subtitle consistent with the Simplified Chinese version — aim for conciseness, do not stuff, and do not include competitor vocabulary.

Why does Apple support multiple languages? Apple is an international company with sales covering 175 countries and regions. E.g. Canada supports English and French; the US accommodates local and immigrant needs; India faces a more complex language environment. Apple currently supports 39 language versions — many regions but fewer language versions, meaning some languages can influence multiple regions. Apple divides the world into 5 macro-regions: North America, Asia-Pacific, Europe, Latin America & the Caribbean, and Africa-Middle East & India.

Setup method: when creating a new app in App Store Connect, select the primary language; go to the App Information page, click the language option on the right, and you can add/remove localized languages.

**(2) Using the developer name**

The developer name is also indexed by Apple. Developer info can be retrieved by Apple and treated as important keyword entry. A developer account is implicitly judged by Apple across multiple dimensions — product weight, product traffic, number of apps under the account, contributed revenue — giving low/medium/high keyword coverage results.

Note: some developers who discovered this rule changed the name into a long string of keyword groups and were later penalized by Apple. An individual account name is fixed and cannot be changed; a company account can be changed to a Chinese company name — especially when the app name and the company brand differ, this directly helps cover the company brand.

**(3) Using IAP info**

You can set up to 20 IAPs and subscription items, each with a name, description, and icon. Keywords in IAP titles are indexed and appear in search results. Case: when searching "股票"/"炒股", the subscription items of financial apps like 同花顺 appear in the ranking results. When searching a brand name, the IAP item ranks #2, which is favorable for brand protection.

### 10.3 Layer 3: meta-rules — Chinese word segmentation and indexing sources

Meta-rules are not only the App Store's rules but the underlying logic and algorithms that support how the internet world works. Meta-rules are the "rules of the rules". This focuses on two underlying rules related to ASO keyword coverage: Chinese word segmentation and the scope of Apple's retrieval.

After mastering this underlying logic, you can progress from "knowing that" to "knowing why". Case: following this method, one app's keyword coverage rose from 5,000 to over 20,000, peaking at 23,000, finally stabilizing at 22,000.

The third layer of skill is directly reflected in keyword grouping and splitting. Within the 100-byte space, how to select and order words is the content of layers 1 and 2 — but how to split and group words is the third layer. Word selection, ordering, and grouping affect not only keyword coverage but also the weight relationship between keywords and the product.

**[Chinese Word Segmentation in detail]**

Chinese word segmentation is splitting a string of Chinese characters into independent, meaningful words. Unlike English, Chinese is a continuous sequence of characters with no natural separators between words, so Chinese segmentation is far harder.

Example: the English "Chinese word segmentation" is three words separated by two spaces — Chinese, word, segmentation. But the Chinese independent characters are "中、文、分、词" and the computer needs an algorithm to determine how to combine them.

Common segmentation algorithms fall into three categories:
- **(a) Dictionary-based a-priori segmentation**: match against a "large enough" dictionary.
  - Forward maximum matching (left to right) — e.g. "量江湖是一家大数据公司" → "量/江湖/是一/家/大数据/公司"
  - Backward maximum matching (right to left) — e.g. "量江湖是一家大数据公司" → "量/江湖/是/一家/大数据/公司"
  - Minimum segmentation (fewest words cut) — e.g. "量江湖是一家大数据公司" → "量江湖/是/一家/大数据公司"
  - The four rules of the MMSEG disambiguation algorithm: ① maximum matching — pick the longest word group; ② maximum average word length; ③ minimum variance of word length (standard deviation); ④ maximum sum of the natural log of single-character word frequencies.
- **(b) Statistics-based learning segmentation**: the more frequently adjacent characters co-occur, the more likely they form a word. Pros: not limited to a text domain, no specialized dictionary needed. Cons: needs annotated corpora, slow, resource-heavy.
- **(c) In practice, the two are combined.**

The significance of understanding Chinese segmentation for ASO: Apple uses a Chinese word-segmentation algorithm to process developer-submitted metadata text in the China App Store. Understanding how Apple splits and combines keywords lets you better design keyword arrangements to produce more effective combination coverage.

### 10.4 Practical word-splitting and word-grouping cases (CN book, Ch. 4 §4)

Based on understanding the meta-rules, you can work on two dimensions:

**Dimension 1 — the space dimension (compressing space):**

At the second level of insight you can easily achieve over a thousand keyword coverages. To get more, one method is to compress existing keywords to free up more space.

Three-step space-compression method (example: a cars app):
- **Step 1: remove duplicate keywords.** Duplicate keywords do not stack the weight Apple assigns and should be deleted. Result: "slimmed" from 87 characters to 61 characters, 18 keywords total.
- **Step 2: group words by heat and relevance.** Combine high-heat keywords first, generally grouping 3-5 keywords into one longer phrase: `汽车买卖查询测评大全，资讯咨询大众宝典，在线估价报价服务平台，头条爱卡软件`
- **Step 3: remove commas.** A comma's purpose is to tell Apple "this is an exact keyword". But from coverage data on tens of thousands of keywords, Apple's algorithm does mix-and-match on keywords. From a Chinese-segmentation standpoint, in general the presence or absence of commas makes little difference.
  - When to use commas: ① in the user-visible app name and title, for readability; ② in English keyword settings, replace spaces with commas to increase word-grouping efficiency; ③ for keywords your own product struggles to cover, separate with commas as a weighting treatment.
  - After removing commas: character count dropped from 61 to 34.

### 10.5 The power of time — accumulating high-weight keywords

**Dimension 2 — the time dimension:**

Beyond considering the developer's claims about keyword coverage across various channels, Apple also considers users' "votes". After several version iterations, some keywords form a strong association with the app — even if removed from the back end, they can still be picked up by Apple's index.

Method: patiently compare the impact of each keyword change on the coverage count, slowly identify your app's "high-weight" keywords, and build a "high-weight keyword list".

Over time, the longer this list, the more room you have to operate ASO, and the more keywords you may cover.

Case: one product's keyword-coverage optimization journey:
- Initial (2020-10-10): 300 words covered
- One month later: over 3,000 words covered
- Two more months: over 10,000 words covered
- Finally stabilized at 13,000 keywords covered

---

## §11. ASA data feeding back into keyword optimization (CN book, Ch. 4 §5)

Chapter title: "Jump outside the three realms, stay out of the five elements" — meaning you must constantly examine the prerequisites of every method. In ASO keyword optimization, one major condition change is the arrival of ASA (Apple Search Ads).

Search keywords' contribution to traffic follows the "80/20 principle" (20% of keywords contribute 80% of traffic). On the App Store this is even more extreme — very likely 0.1% of keywords contribute over 80% of traffic, but you do not know which words.

ASA's arrival brings a new variable: in the past there was no quantitative basis to judge how much exposure, downloads, and conversion certain keywords could bring; now this can be obtained indirectly through ASA campaign data.

Case: 美团's coverage data in the China App Store — total coverage of 7,769 keywords, of which 97 have heat above 4605 and rank in the top three.

What is more meaningful is to further ask:
1. Which words bring how many downloads each?
2. Which words have good ROI or retention?
3. Which words have a high conversion rate?

ASA's attribution data can answer these questions, leading to a re-understanding of the value standing of these 97 words, returning to the word-grouping and word-selection stage to re-adjust the selection and ordering of words in the Apple back-end keyword settings.

---

## §12. Conversion value (Value_Rate) — creative-asset and copy optimization methodology (CN book, Ch. 5)

Chapter 5 of the CN book specifically explores the other part of ASO's value — conversion value — by producing user-facing ASO copy and assets to attract user attention and improve dwell time and conversion efficiency. Unlike the engineering mindset that explores traffic value, this part is a humanities mindset — based on understanding human nature and the way the brain cognizes.

**The current state of ASO asset production:**
Companies currently emphasize `Value_Traffic` (keyword coverage and traffic acquisition) and neglect `Value_Rate` (copy and asset production). Reasons:
- First, keyword-coverage optimization has an intuitive effect and a quantitative standard.
- Second, conversion-rate optimization lacks quantitative means, and even when effective is not easily tied to KPIs.

The deeper reason: conversion-rate optimization lacks a systematic methodology; existing methods stay at the "borrow" (copy competitors) and "be different" (make something different) stages.

**The core problem — an asymmetry of cognitive background**: there is a serious cognitive gap between professionally-trained designers and product managers and the users who glance by in a hurry. Operations staff in internet companies know product and operations knowledge inside out, but are powerless facing novice users — they lack what Zhang Xiaolong called the ability to "instantly become a novice".

**The solution methodology — the four-step iteration method:**
"Instantly become a novice → user logic → story thinking → produce assets"

The theoretical basis involves two important models in cognitive science:
1. Daniel Kahneman's Dual Process Theory
2. Baddeley's Working Memory Theory

**Goal**: enable an ordinary ASO optimizer to develop the ability to "instantly become a novice" in a short time, and to low-cost produce high-conversion ASO assets — including icon, title, subtitle, and screenshots/video.

This methodology fuses cross-disciplinary knowledge from computer science, logic, cognitive science, and rhetoric, aiming to systematically improve app download conversion rate.

---

*=== End of document ===*

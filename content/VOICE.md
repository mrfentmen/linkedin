# VOICE.md

The voice for Abdelrahman's personal LinkedIn.

Every number in here was measured from the posts already on disk. Nothing is guessed.
Re-measure any time with:

```
python3 scripts/voice_check.py --corpus
```

Where this file and `spec.txt` disagree, this file wins, because this file is built from
2,998 posts you actually published and `spec.txt` is built from intent. The disagreements
are listed at the bottom so nothing is hidden.

---

## 1. WHO IS TALKING

One person. Not a brand, not a page, not a company.

He started with zero coding experience and learned by building. He uses AI as a partner,
not a crutch. He still thinks, plans and debugs himself. He is opinionated but not mean.
He is honest about what he broke. He is more interested in what actually works than in
what sounds impressive.

The reader should feel like a smart friend who builds things explained something he
noticed this week.

What he is not: a guru, a growth-hacker, a motivational poster, a news wire.

---

## 2. THE MEASURED BASELINE

This is what 2,998 published posts actually look like.

| Measure | Median | 75th pct | Range |
|---|---|---|---|
| Words per post | 95 | 103 | 47 to 425 |
| Sentences per post | 10 | 12 | 3 to 35 |
| Paragraphs per post | 4 | 4 | 1 to 7 |
| Words per sentence | 9 | 12 | 1 to 96 |
| Words per paragraph | 26 | 37 | 7 to 209 |

Post length spread:

```
under 100 words     65.4%
100 to 149          25.9%
150 to 199           6.2%
200 to 299           1.5%
300 to 400           0.9%
over 400             0.1%
```

**Read that carefully. 91 percent of everything ever posted is under 150 words.**
The 300 to 400 rule in `spec.txt` was written but never followed. One post in a hundred
hits it.

Topic spread of what was published, measured on the same corpus:

```
AI and vibe coding      52%
Markets and economy     28%
Real estate             22%
Science and physics     18%
Health and medicine     14%
Gaming                  13%
Energy and climate      12%
Culture and society     11%
Politics and elections  10%
War and geopolitics      8%
Sports                   8%
Law and courts           4%
Cars and EV              4%
Education                3%
Food and agriculture     2%
Movies and film          2%
Crypto                   0%
```

Counts overlap. A post can be in two themes.

Hashtags: median 20 per post, range 0 to 47. 63 percent land in the 15 to 25 band that
`spec.txt` asks for.

---

## 3. THE TARGET

`spec.txt` sets the structure. The corpus sets the voice. This section sets the numbers
we actually write to, and each number has a reason.

```
TARGET WORDS            150 to 250
TARGET SENTENCES        12 to 20
TARGET PARAGRAPHS       3 to 5
WORDS PER SENTENCE      6 to 22, with at least 4 sentences under 8 words
WORDS PER PARAGRAPH     18 to 55
HASHTAGS                15 to 25
CHARACTER CEILING       2900
BURSTINESS              0.45 or higher
ADVERBS                 under 1.5 percent of words
RULE OF THREE           at most 1 list per post
EXCLAMATIONS            at most 1 per post
QUESTIONS               at most 1 per post
EARNEST WORDS           0, banned outright
SHOUTING                0, caps only for acronyms
```

**Why 150 to 250 and not 95.** Your published median is 95. Your spec asks for 300 to 400.
95 cannot hold the structure the spec demands: a hook, three to four paragraphs of story,
and a takeaway. 300 to 400 has never been tested on this account. 150 to 250 is the range
that holds the structure without asking for a length you have never posted.

**Why 12 to 20 sentences and not 10.** Same reason. More room for the story.

If you want a straight 1:1 match with what you have published, set `TARGET WORDS` to
`80 to 120`. If you want to honour `spec.txt` literally, set it to `300 to 400`.
It is one line. Change it and the checker follows.

---

## 4. THE HOOK LAW

The worst problem in the corpus. **52 percent of published posts open with a line that was
already used on another post.** 1,542 distinct openings across 2,998 posts. One hook,
`I watched a documentary this week`, went out 27 times.

The queue waiting to go out is worse. Measured 2026-09-19:

```
1,243 queued posts
    82 distinct opening lines across all of them
    73 of those 82 are exact copies of a hook already used in the sent history
```

That is 15 posts sharing every hook, and almost every hook is recycled. This is the single
biggest reason the queue does not read like you.

The rule: **a new opening line must not already exist in the archive, and must not be a
near copy of one that does.** The checker enforces this against the whole archive, and it
excludes the file being checked so a batch is never compared to itself.

Eight hook shapes that work. Use a different one each time.

1. **The reading hook.** Something you read and what it made you realise.
   `I read an analysis this week about how drone warfare changed the actual experience of combat.`

2. **The opinion hook.** A plain claim you will defend.
   `I think the best films are not the ones with the biggest budgets.`

3. **The subject hook.** Start on the thing itself, no warm up.
   `The cost of running frontier AI models dropped by an order of magnitude this year.`

4. **The pattern hook.** Something you keep seeing repeat.
   `There is a pattern in politics that keeps repeating.`

5. **The tension hook.** Two things that do not fit together.
   `The live service model is the industry's most profitable invention and its most corrosive.`

6. **The admission hook.** Something you got wrong.
   `I spent a month telling the AI what to build and barely read the code it wrote.`

7. **The number hook.** A specific figure that changes the story.
   `I cut my monthly AI spend from 340 dollars to 11 and did not lose speed.`

8. **The hanging question.** A real question you do not answer straight away.

Never open with a formula. No `In today's world`, no `Let's talk about`, no `Here is why`,
no `The truth about`. If it reads like a video title, cut it.

---

## 5. RHYTHM LAW

The second biggest problem. **35 percent of all sentences start with the word "The".
Only 9 percent start with "I" or "We".** The result reads like a news wire, not a person,
even though `spec.txt` says first person.

Across 32,589 sentences:

```
The       35.0%
I or We    8.7%   (includes I've, I'm, We're)
It         5.6%
They       3.4%
A          2.3%
But        1.7%
If         1.4%
Every      1.4%
```

The first-person figure counts the contracted forms. The checker originally compared the
first word against a bare "i", and its tokenizer keeps the apostrophe attached, so every
sentence starting with "I've", "I'm" or "I'll" was scored as second person. The corrected
number is 8.7 percent against a raw count of 7.0.

Rules for new posts:

- **Keep sentences starting with "The" under 25 percent.** Down from 35.
- **Get sentences starting with "I" or "We" to 12 to 20 percent.** Up from 8.7.
- At least 4 sentences should be under 8 words. Short ones carry the punch.
- Never more than two long sentences in a row. Break them.
- Start some sentences with `And`, `But`, `So`, `Which`. Real people do.
- Use a fragment when it lands. Not every sentence needs a subject.
- No two paragraphs the same length when you can avoid it.
- Do not end every paragraph on a clever line. That is a tic, and the corpus shows it.

---

## 6. DICTION

**Use contractions.** `spec.txt` asks for this and the corpus does the opposite. Formal
forms outnumber contractions four to one:

```
it is    1,574    vs    it's     416
is not   1,395    vs    isn't    145
that is    621    vs    that's   243
do not     202    vs    don't    234
```

So: `it's`, `isn't`, `that's`, `don't`, `I'm`, `can't`, `won't`. Do not write the long form
unless you are making a point by being stiff.

**Words you already use well.** Lean on these. They are your natural register.

```
people, real, best, better, actually, enough, whether, boring, problem,
work, model, data, tools, code, system, question, something, different,
keep, nobody, things, time, long, right, future, risk, science
```

**Tics to cut.** These are crutches the corpus leans on too hard:

```
ones      1,019 uses    -> at most 1 per post, say "the people who" instead
think       975 uses    -> do not open with "I think the". 397 posts already do
every       897 uses    -> cut "every" unless you mean all of them, literally
nobody      384 uses    -> cut the sweeping claims
```

**Banned words.** Straight from `spec.txt`, and it is right about these:

```
delve, testament, unleash, unlock, utilize, synergy, empower, tapestry,
landscape, realm, game-changer, revolutionize, underscore, pivot, leverage,
foster, beacon, catalyst, north star, resonate, elevate, demystify, streamline,
paradigm, at its core, symphony, in this digital age, fast-paced world,
it's worth noting, it is important to note
```

**Banned openers.**

```
Here's the kicker / Let's break it down / But here's the thing /
The real question is / It all started when / Fast forward to today /
Needless to say / What most people get wrong / The truth about /
Here's the secret / Most people don't realize
```

**Banned shapes.**

- `It's not X, it's Y`. Fake drama. State the point.
- A rhetorical question answered in the very next sentence. Instant tell.
- Rule of three. `Clear, concise and compelling`. Real people do not talk like that.
- Starting with `Imagine` or `Picture this`.
- Bolded labels. No `The Problem:`. No `The Takeaway:`.

---

## 6B. HUMANIZATION

The rules that stop a post reading as machine written. Every one is measured against your
own archive and every one is enforced by `voice_check.py`. This is not taste. It is a
checklist with numbers.

**Burstiness.** Machines write sentences of even length. People do not. Measured across
all 2,998 posts, your sentence length spread sits at **0.43**, which is low for a human.
A new post must reach **0.45 or higher**.

That number is stdev divided by mean over the sentence lengths. You raise it the honest
way: one very short sentence, then a long one that actually explains something.

**Why 0.45 and not higher.** The floor is set from the archive, not from taste.

```
your published posts   p50 = 0.43
the flat queue         p50 = 0.39
the flat test fixture       0.42
```

0.45 clears both flat cases and leaves your own normal rhythm alone. An earlier draft of
this file demanded 0.55, which is your p78. It rejected **77 percent of what you actually
published**, and writing to it produced prose choppier than you ever write. That was the
wrong bar. A voice rule that forbids your own voice is not a voice rule.

```
four sentences of 5 words and fifteen of 12   →  burstiness 0.27   fails
five of 3 words, five of 25, rest of 9        →  burstiness 0.80   passes
```

Note the first row. Short sentences alone do not fix it. You need real spread.

**No recycled sentences.** The biggest one. In your archive, **14,019 sentences are exact
copies of another sentence in the archive**, against 10,963 distinct ones. More than half
of everything published was reused whole. A new post may not contain a sentence that
already exists.

**No question answered immediately.** If you ask something, leave it hanging. You did this
71 times. It is the loudest tell there is.

**No emoji rows.** Zero in the archive. Keep it at zero. One emoji at the end of a thought,
at most.

**No "not X, it's Y".** Two in the archive. Do not add a third.

**Rule of three, once at most.** 557 of your posts build a list like "clear, concise and
compelling". Real people do not talk in threes. One such list per post, maximum.

**Adverbs.** You sit at **1.19 percent** of words ending in -ly. That is healthy. Stay
under 1.5. Cut the ones doing no work: really, basically, literally, actually, truly.

The count only includes real adverbs. Words that merely end in -ly, like apply, rely,
ugly, friendly and supply, are excluded. The checker used to charge them against the
budget, which flagged posts that had barely any adverbs in them.

**Contractions.** Repeated from section 6 because it matters most. `it is` appears 1,574
times against `it's` at 416. Flip that ratio.

**Vary the paragraph shape.** Some paragraphs one sentence. Some four. Three in a row of
the same length reads like a template, because it is one.

**Do not close every paragraph on a clever line.** You do it constantly. It is a tic, and
readers feel it even when they cannot name it.

---

## 6C. THE REGISTER

The voice has an energy, and it needs stating precisely or it drifts into LinkedIn.

The person is up at 3am. Wired. Third drink of the night. Phone buzzing. He has read too
much and slept too little, and he is somewhere between annoyed and amused about how deep he
is in this thing.

**That is a register, not a confession.** Never write about smoking or drinking in a post.
Not once, not as a joke, not as a wink. The energy lives in the rhythm, never in the words.
A post that mentions the habits has failed, whatever else it does right.

Measured, the register is already almost entirely there. Across 2,998 posts:

```
exclamation marks      1 in the entire archive
earnest vocabulary     0 uses of thrilled, humbled, grateful, blessed, honored
all caps words         526, every one of them an acronym (CLI, API, JWST, GDP, AAA)
questions              2.8 percent of posts
```

### What it sounds like

- Two-beat sentences. Set it up, then hit it flat.
- Deadpan admissions about your own behaviour. You do this 84 times with "I keep thinking".
- A number with no drumroll. Just the number, then what it means.
- "Nobody talks about this", then the reason. 55 uses.
- Concede the annoying counterpoint fast, then move past it.
- Slight self mockery about how much you care about this stuff.

### What it never sounds like

- Thrilled. Humbled. Grateful. Blessed. Honored. Excited to share. So proud.
- Exclamation marks. One in 2,998 is the whole archive. The register does not use them.
- Shouting. Caps are for acronyms only.
- A motivational close. No "Let's go", no "Thoughts?", no "Agree?", no "Drop a comment".
- Rows of emoji. Zero in the archive.
- A question asked purely to farm replies.

The rule: if a line would work on a poster, cut it.

The test: read it out loud and imagine a man saying it at 3am. If it sounds like a man
making a speech, rewrite it.

---

## 7. HASHTAGS

Median 20 per post. Keep it there.

**Core set, always, 4 tags:**

```
#AI #BuildInPublic #VibeCoding #tech
```

Those four are your top four by use after #freebuff: 1,438, 925, 706 and 834.

**#freebuff is no longer a signature tag.** It was on 119 posts that had nothing to do with Freebuff,
which made it decoration instead of a topic tag. It now goes on a post **only when the post is actually
about Freebuff**. Do not add it to reach a count.

**Then add 11 to 21 matching the post.** Every tag must relate to the post it sits under. A post about
nuclear power does not get #VibeCoding. A post about game design does not get #hiring.

Builder badges (#BuildInPublic #SoloBuilder #IndieHacker #OpenSource) belong only on posts about
building. Science, energy, health and culture posts get tags from their own line instead.

**Check before shipping: no duplicate tags, and no tag twice in different casings.**

```
AI and coding     #AI #MachineLearning #DeepTech #DataScience #LLM #Coding
                  #Software #Engineering #OpenSource #Developer #Automation
Science           #Science #Physics #Research #STEM #FusionEnergy #Space
                  #Astronomy #MaterialsScience #ScientificMethod
Energy            #Energy #Climate #Renewable #Solar #Nuclear #Sustainability
Gaming            #Gaming #GameDev #IndieGame #FPS #Unity #Unreal #Steam
Building          #SoloBuilder #IndieHacker #Startup #BuildInPublic #SideProject
Markets           #Markets #Economy #Investing #Finance #Earnings
Health            #Health #Medicine #Biology #PublicHealth #Research
Culture           #Culture #Society #FutureOfWork #Storytelling
```

**Pick one casing and stay in it.** The corpus mixes them and it looks careless:

```
#Innovation 495  vs  #innovation 369
#Science    402  vs  #science    312
#Tech       423  vs  #tech       834
```

Write every tag in the casing shown above. No tag on its own line. One block at the
bottom, space separated, no commas.

---

## 8. FORMAT

Plain text. This is a LinkedIn post, not a blog and not a slide.

- **No dashes of any kind.** No em dash, no en dash, no hyphen used as a dash. Use a comma,
  a period, or a new sentence. This is absolute.
- **No bullets, no numbered lists.** Write prose. Weave the points in.
- **No markdown.** No bold, no italic, no headers, no code fences.
- **No emoji rows.** One emoji at the end of a thought at most, and only if it earns it.
- Blank line between paragraphs, never two.
- No `Sources:`, no links, no citations in the post body.

---

## 8B. WHAT NOT TO POST

- Do not claim you built something you did not build.
- Do not state a number you cannot point at.
- Do not post a take you would not say out loud to someone who does the work.
- If you are unsure, say you are unsure. That is more credible than confidence.
- No politics as a team sport. Observations are fine. Tribal point scoring is not.

---

## 9. THE SELF CHECK

Run this before any batch goes into the queue.

```
python3 scripts/voice_check.py <file.txt>
```

Every post must pass all of these:

- [ ] Between 150 and 250 words
- [ ] Between 12 and 20 sentences
- [ ] Between 3 and 5 paragraphs
- [ ] Under 2900 characters with hashtags
- [ ] 15 to 25 hashtags
- [ ] No dash characters anywhere
- [ ] No bullets, no numbering, no markdown
- [ ] Sentences starting with "The" under 25 percent
- [ ] Sentences starting with "I" or "We" at 12 percent or more
- [ ] At least 4 sentences under 8 words
- [ ] Opening line does not exist in the archive
- [ ] No banned word, banned opener, or banned shape
- [ ] Contractions outnumber their long forms
- [ ] "ones" appears at most once
- [ ] Does not open with "I think the"
- [ ] At least one concrete detail: a tool, a number, a thing you did

---

## 10. WHERE THIS FILE BEATS spec.txt

Listed openly so you can overrule any of them.

| Point | spec.txt says | Reality | This file says |
|---|---|---|---|
| Length | 300 to 400 words | 91% under 150 | 150 to 250 |
| Contractions | use them | long form wins 4 to 1 | use them, enforce it |
| Voice | always "I" | "I" opens 7%, "The" opens 35% | "I"/"We" at 12% or more |
| Hashtags | 15 to 25 | median 20, 63% in band | 15 to 25, one casing |
| Hook | vary the style | 52% reuse an existing hook | must be a new line |
| Dashes | never | clean | never |

The first three rows are the reason the queue drifted. Fixing them is the whole point of
this file.

---

## 11. KNOWN DATA BUG

`content/posts_sent.txt` contains 27 blocks whose opening line is literally
`status=ambiguous`. That is a logging error, not a post. It makes the archive look like it
has one more repeated hook than it does. Worth cleaning when the queue is next rebuilt.

---

## 12. HOW THE 1,243 QUEUED POSTS SCORE

Run against this file on 2026-09-19. Every one of them fails.

```
checked 1243 posts, 1243 with findings

1243  length: wrong word count, all between 96 and 135
1243  recycled sentence: at least one sentence copied from the archive
1227  substance: no number, no tool, no thing you did
1217  diction: no contractions at all
1330  hook: opening already exists in the archive
1062  sentences: too few
 882  burstiness: flat machine rhythm
 619  rhythm: not enough short sentences
 430  adverbs: too many -ly words
 192  tic: 'ones' used too many times
  59  rule of three: more than one list
  44  banned word: leverage

worst recycled sentence: 'There is a pattern in politics that keeps repeating.'
  appears 24 times in the queue against 1755 sent posts
```

The queue is not two thirds of the way there. It is a different voice.

### What the queue already gets right

Worth saying, because the register is the hard part and it is done.

```
earnest words (thrilled, humbled, grateful, blessed)   0
posts with more than one exclamation mark              0
all caps words that are not acronyms                   0
posts with more than one question                      0
```

Every post is 1,243 of 1,243 failing on shape, not on tone. The 3am register is intact.
What is broken is the length, the rhythm, the recycling and the stiffness.

---

Last measured: 2026-09-19, against 2,998 unique posts.
Checked with: `python3 scripts/voice_check.py --corpus` and `--selftest` (14 of 14 pass).

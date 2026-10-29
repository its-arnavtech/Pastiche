# Legal paths for a commercial profile

> **This is not legal advice.** It is an engineer's map of the options, written so that a qualified lawyer (music and
> software licensing) can be briefed quickly. Nothing here has been reviewed by one. Copyright, performance rights, sound
> recording rights and neighbouring rights differ by country. **Do not launch publicly, or ingest anyone else's music on a
> server, until this has been reviewed.**

## The problem

StemDNA separates recordings into stems and recombines pieces of them into new tracks. Both steps make **copies and
derivative works of copyrighted sound recordings** (and the compositions on them). On a server, with many users, that is a
serious legal problem, and it is the gating issue for POC 2. The software design cannot fix it. The ways around it are about
whose copy it is, and who has granted what.

## Path (a): on-device processing of the user's own files

**What it is.** The user's music never leaves their device. Separation, analysis, embedding, planning and rendering run on the
user's machine (as POC 1 already does on the owner's laptop). The server holds only things that are not recordings: recipes
(lists of "which stem, which time range"), ratings, events, taste vectors, insights.

**Fits the code.** Strongest fit. POC 1 is this path. The local profile is the product; a hosted profile would only sync recipes
and events (small, no audio).

**Open questions for a lawyer.**
- Is a private, personal-use remix of files the user already owns covered where they live (private copying exceptions exist in some
  countries and not in others; they often exclude circumventing copy protection)?
- If the user shares a rendered remix, that is distribution; the product should not make sharing audio easy by default.
- Software distribution: the app ships Demucs (MIT), CLAP (Apache-2.0) and Pedalboard (**GPL-3.0**, see `docs/licenses.md`).
  A distributed binary triggers the GPL; a hosted one does not.
- Compute: users need a capable GPU (or accept slow CPU separation). On the laptop measured here, light Demucs runs at about 58
  audio-seconds per second.

**Cost.** Lowest to the operator (`docs/unit-economics.md`, "on-device" rows): events and recipes only.

**Risks.** Weakest product: no shared catalog, no discovery, quality depends on the user's hardware. Support burden for installs.

## Path (b): licensed, royalty-free or Creative Commons catalogs

**What it is.** The service ingests only audio whose terms permit it, separates it once, and serves stems and remixes to everyone.

**Fits the code.** Good. Separate-once-cache-forever pays off because one catalog serves all users; the shared catalog cost
model is in `docs/unit-economics.md`.

**What "permitted" must mean.** Check each source, per track or per catalog:
- It allows **derivative works** (not only copying). Creative Commons **ND** (no derivatives) licenses do not. **NC**
  (non-commercial) licenses do not fit a commercial service. **SA** (share-alike) obliges the output to carry the same license, which
  affects remixes users share. **BY** needs attribution, so recipes must carry per-song credit (the recipe already records every
  song used, which helps).
- It covers both the **recording** and the **composition** (a free recording of a copyrighted song is not free to remix).
- The licensor actually holds the rights (uploaders to open catalogs sometimes do not). Keep the license text and the source
  URL per track; a takedown path is needed.
- Terms of the catalog's own site (scraping and bulk download are often prohibited even for open content).

**Candidate sources to evaluate (nothing checked or contacted):** public-domain recordings (jurisdiction-dependent), catalogs of
CC0 and CC-BY music, royalty-free production-music libraries with an explicit derivative-works and commercial-use grant, and
stems that rights holders publish for remixing.

**Cost.** Catalog licenses may cost money. The compute and storage for a catalog of 10,000 tracks is small
(`docs/unit-economics.md`).

**Risks.** A catalog of free music may not be what users want; attribution and license tracking are ongoing work.

## Path (c): a direct licensing agreement

**What it is.** A deal with a label, publisher, distributor or an aggregator that grants the right to separate and recombine
specific works, with reporting and royalty terms.

**Fits the code.** The code needs per-song usage accounting (the lineage index and events already record which songs and
windows were used in which recipes and how often they were played), which is what a licensor asks for.

**Reality.** Needs money, a legal entity and a lawyer, and licensors rarely grant derivative-works rights to an unproven product.
Not available at a $0 budget. Treat it as a later step once path (a) or (b) has users.

## Comparison

| | (a) on-device | (b) licensed / CC catalog | (c) direct license |
|---|---|---|---|
| Copyrighted audio on the server | none | only cleared audio | licensed audio |
| Legal risk to the operator | lowest | low if terms are checked per track | lowest once signed |
| Budget needed now | $0 | $0 for CC0 / CC-BY, more for paid libraries | significant, plus legal fees |
| Product reach | personal tool | shared catalog, limited music | full catalog |
| Compute per user | on the user | operator (one-off per track) | operator |
| Reuses POC 1 unchanged | yes | yes, plus a license ledger | yes, plus reporting |

## Recommendation (an engineering opinion, not advice)

Ship path (a) first: it is what POC 1 already is and it keeps copyrighted audio off any server. Add path (b) for a shared catalog
only with a per-track license ledger. Keep path (c) as a growth option. In every path: do not upload users' music to the operator's
servers, do not let one user's separation be reused for another user (the POC 2 spec allows sharing only "where licensing permits"),
and keep the per-song deletion path (`delete_track`, `delete_tenant`) working, since takedowns will happen.

## Things to bring to a lawyer

1. Is a personal, on-device remix of owned files lawful in the launch countries, and can the software be distributed under GPL-3.0
   terms (or must Pedalboard and Rubber Band be replaced or licensed)?
2. For a CC catalog: which licenses allow separation plus recombination plus commercial service, and how must attribution be
   shown for a remix of 10-20 songs?
3. Are model weights trained on copyrighted music (Demucs, CLAP) a concern for customers or for the operator?
4. Privacy: ratings and listening events are personal data (consent, export, deletion, children).
5. What a takedown process must look like and how fast.

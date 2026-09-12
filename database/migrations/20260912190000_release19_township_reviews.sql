-- ============================================================================
-- Migration: release19_township_reviews
-- Description: The township-by-township restriction review for every Ohio
--              township governing surveyed parcels — 28 rows, each citing
--              the township's own record or reputable coverage naming the
--              action, date and vote.
--
--   Release18 wired the moratorium gate and left every Ohio township
--   unreviewed: 1,966 Licking and 982 Franklin parcels read UNKNOWN
--   because "a jurisdiction nobody has reviewed reads UNKNOWN, never
--   PASS". This batch is the review that replaces those UNKNOWNs with
--   decided verdicts.
--
--   What the review found:
--     * Licking: Harrison Township adopted zoning text amendments on
--       2026-07-06 (3-0) striking the Zoning Commission's proposed M-1
--       conditional use "Data Centers" and the proposed DATA CENTER /
--       DATA CENTER CAMPUS definitions — no data-center authorization
--       exists anywhere in its resolution. Every other Licking township
--       checked clear.
--     * Franklin: Jackson (one-year pause, 2026-05-12), Pleasant
--       (Resolution 11, 2026-02-24, no stated expiry), Washington
--       (90-day pause 2025-12-09, extended to 2026-09-05) and Prairie
--       (Resolution 18-26, six months from 2026-04-15) all adopted
--       moratoria; the other eleven checked clear.
--
--   Two scope decisions the rows encode:
--
--   1. A township-wide exclusion is a restriction-layer row; a
--      district-level use-table fact is not. Harrison's amendment leaves
--      data centers unauthorized in every district — the same class as
--      St. Albans (release17b), recorded 'adopted' and binding on its
--      parcels. Etna's August 2026 "Harvey Farms" text amendment removes
--      data centers from General Business districts ONLY, and its
--      ordinance continues to allow them in industrial and overlay
--      districts — a use-table fact the county mapping already carries
--      (GB1 prohibited since 2026-township-reviewed), so Etna reads
--      none_found at the township level with the amendment recorded in
--      its basis. Failing Etna's industrial parcels on a GB-district
--      amendment would be the wrong jurisdiction claiming the wrong land.
--
--   2. The calendar decides, and derived expiries are dated. Jackson's
--      letter says "one-year moratorium" adopted 2026-05-12, so
--      expires_date is the arithmetic 2027-05-12 (derivation stated in
--      the basis); Prairie's resolution says six months from 2026-04-15,
--      so 2026-10-15. Washington's verified record ends 2026-09-05 — the
--      Sept 8, 2026 agenda lists a further extension but its minutes
--      were not yet posted, so the extension is unrecorded and the row
--      reads lapsed as of a 2026-09-12 run: CONDITIONAL, the row
--      surviving as the political-risk signal it is.
--
--   Incorporated places are NOT reviewed here — Columbus, Newark, Abilene
--   et al. remain unreviewed rows away, and their parcels stay UNKNOWN.
--
--   Also in this migration: a third Licking zoning use-table version.
--   The brief's own rule — "that township's constraint_rules row must
--   carry the removal" — applies to Harrison's M-1: the flat by_right
--   M-1 entry (supported by other townships' resolutions) must not
--   decide Harrison's M-1, where the use is not listed. A scoped
--   district class ("M-1|Harrison": prohibited) fixes the 13 affected
--   parcels; every other mapping is unchanged from
--   2026-township-reviewed2, which this row supersedes.
--
--   Applied to production 2026-09-12.
-- ============================================================================

-- ── Licking County townships (13) ─────────────────────────────────────────

INSERT INTO public.jurisdiction_restrictions
    (state_code, county_name, subdivision_name, status, instrument, adopting_body,
     adopted_date, effective_date, expires_date, scope, source_url, basis,
     reviewed_at, sources_checked)
VALUES
('OH', 'Licking', 'Liberty township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://libertytwplickingco.com/announcements/',
 'The township''s own announcements 2024-2026 show only procedural zoning amendments (public-notice provisions, plan-copy requirements, home-occupation definitions) and unrelated rezonings; no data-centre moratorium or text amendment appears in any notice, and no reputable outlet reports this Liberty Township acting. Decoy rejected: the June-July 2026 "Liberty Township" data-centre zoning votes (WCPO/WVXU/journal-news) are Butler County''s Liberty Township.',
 '2026-09-12',
 'libertytwplickingco.com/announcements/ (all notices 2024-2026); libertytwplickingco.com zoning-amendment public-hearing notices (2024-11-18, 2025, 2026-04-21); lickingcounty.gov/depts/planning/zoninginfo/liberty.htm; searches "Liberty Township Licking County data center moratorium", "libertytwplickingco.com data center zoning"'),

('OH', 'Licking', 'McKean township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://mckeantownship.net/minutes/monthly-minutes/',
 'The township''s own minutes from July 2025 through August 2026 are routine township business — roads, cemetery, zoning permits; the Aug 6, 2026 special meeting was solely the chip-and-seal of Riley and Lafayette Roads (Resolution 2026-5). No data-centre moratorium, pause, or text amendment appears, and no news coverage of McKean trustees acting was found. Decoy rejected: mckeantownship.com is McKean Township, Erie County, Pennsylvania.',
 '2026-09-12',
 'mckeantownship.net (home, monthly-minutes index, 2026-08-06 special meeting read in full, zoning resolution); lickingcounty.gov/depts/planning/zoninginfo/mckean.htm; searches "McKean Township Licking County data center moratorium", "McKean Township trustees Licking County zoning data center"'),

('OH', 'Licking', 'Harrison township', 'adopted',
 'Zoning text amendments to the Harrison Township Zoning Resolution adopted at the 2026-07-06 public hearing, striking the Zoning Commission''s proposed addition of "Data Centers" as conditional use No. 18 in Article 16.2 (M-1 General Manufacturing District) and removing the proposed DATA CENTER and DATA CENTER CAMPUS definitions from Article 3 — leaving data centers with no permitted or conditional authorization anywhere in the township''s resolution',
 'Harrison Township Board of Trustees (Van Buren, Smith, Foor — 3-0)',
 '2026-07-06', NULL, NULL,
 'Township-wide: data centers are not a listed use in any district of the Harrison Township Zoning Resolution. Verbatim from the trustees'' own minutes: "Article 16.2 Conditional Uses, Number 18. The trustees would like to strike number 18, Data Centers." — motion by Smith, seconded by Foor, "Roll call: Van Buren YES, Smith YES and Foor YES. The motion passed." The Zoning Commission had proposed the additions after its March 2026 consideration; the trustees struck them before adoption.',
 'http://harrisontownship.net/wp-content/uploads/2026/07/MINUTES-2026-07-06-Public-Hearing-Zoning-Amendments.pdf',
 'Verified from the township''s own adopted public-hearing minutes (read in full): the ZC''s proposed revisions, the trustees'' floor changes striking the data-centre conditional use and definitions, the 3-0 roll call, and passage; corroborated by the 2026-03-02 minutes (ZC considering the addition) and the 2026-07-21 minutes (hearing minutes approved). A permanent text amendment, not a pause: no expiry exists. Removal-by-refusal: the use was never listed, and the trustees declined to add it — the net effect is no authorization anywhere in the resolution.',
 '2026-09-12',
 'harrisontownship.net MINUTES-2026-07-06-Public-Hearing-Zoning-Amendments.pdf (read in full); MINUTES-2026-03-02.pdf; MINUTES-2026-06-16.pdf; MINUTES-2026-07-21.pdf; MINUTES-2026-08-03.pdf; harrisontownship.net trustees-meeting-minutes and news-notices indexes; lickingcounty.gov/depts/planning/zoninginfo/harrison.htm; searches "Harrison Township Licking County data center moratorium", "harrisontownship.net data center"'),

('OH', 'Licking', 'Granville township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.granvilletownship.org/zoning',
 'The township re-adopted its complete Zoning Resolution on 2025-12-03 (effective 2026-01-03); the full 7,234-line text contains no data-centre or data-processing restriction, definition, or moratorium, and the township''s site shows no data-centre hearing or amendment. Decoys rejected: granvilletwp.org''s "Data Center Ordinance 2026-02" and the "Granville Township Board of Supervisors" coverage are Granville Township, Mifflin County, PENNSYLVANIA (PA has supervisors; Ohio townships have trustees); the 2026 ballot-petition activity is Granville VILLAGE, a separate jurisdiction.',
 '2026-09-12',
 'granvilletownship.org/zoning; Adopted-Zoning-Amendment-Effective-2026-01-03.pdf (full text searched); granvilletownship.org/current-meeting-information; lickingcounty.gov/depts/planning/zoninginfo/granville.htm; thereportingproject.org St. Albans article (county context); searches "granvilletownship.org data center moratorium", "\"Granville Township\" Licking County data center moratorium 2026"'),

('OH', 'Licking', 'Burlington township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://burlington-township.com/',
 'The township''s own website carries no special notices, minutes, or zoning actions mentioning data centres — only governance and road/cemetery information; its 2023-2025 comprehensive-plan update contains no data-centre restriction. Searches of Newark Advocate, The Reporting Project, NBC4 and Columbus Business First coverage of Licking County data-centre actions surface no Burlington Township trustees'' action.',
 '2026-09-12',
 'burlington-township.com (full site); lickingcounty.gov/depts/planning/zoninginfo/burlington.htm; county comprehensive-plan document (BlobID 49334); searches "Burlington Township Licking County data center moratorium", "Burlington Township trustees Licking County zoning"'),

('OH', 'Licking', 'Bennington township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://benningtontownshiplc.org/',
 'The township''s official site''s only 2026 news item is a Sept 9, 2026 special meeting, read in full: "the purpose of this meeting is to consider road improvements" — nothing data-centre related. The township publishes no data-centre notice, zoning amendment, or moratorium, and no news outlet reports its trustees acting on data centres; its zoning resolution on record (2000/2001, amended 2005) contains no data-processing restriction.',
 '2026-09-12',
 'benningtontownshiplc.org (home, 2026-09-04 meeting post, category archive); lickingcounty.gov/depts/planning/zoninginfo/bennington.htm; energyzoning.org Bennington township zoning resolution; searches "Bennington Township Licking County data center moratorium", "Bennington Township Ohio data center restrictions"'),

('OH', 'Licking', 'Monroe township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.monroetownship.org/notices/',
 'The township has taken no restriction action — its most recent public notice (Sept 9, 2026 hearing) shows it actively PROCESSING a data-centre-adjacent application: a rezoning from R-1 to PUMD at 14270 Fancher Rd (AES Partners LLC). The notices page otherwise carries trash-service announcements and an advocacy notice about state SB 243. Decoy rejected: Food & Water Watch''s "Monroe Township, OH unanimously passes data center moratorium" (2026-03-09) is Monroe Township, Adams County. Residual gap noted: full trustee minutes sit behind a SharePoint link that could not be opened; the public-notices page, which would legally have to advertise any zoning hearing, was checked directly.',
 '2026-09-12',
 'monroetownship.org (home, notices, zoning); lickingcounty.gov/depts/planning/zoninginfo/monroe.htm; searches "Monroe Township Licking County data center moratorium", "Monroe Township Johnstown AES Partners Fancher Road data center"'),

('OH', 'Licking', 'Newton township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://newtontownshiplc.com/zoning',
 'The township''s own zoning resolution (updated June 2018, full text reviewed) contains no data-centre, data-processing, or moratorium provisions, and its 2026 public notices cover only road bids, a farmland lease bid, and a surplus fire-truck auction. No trustee action found; all "Newton" news hits were Newton Falls (Trumbull County) or Newton County, Georgia — different jurisdictions.',
 '2026-09-12',
 'newtontownshiplc.com/zoning (Zoning Resolution PDF, full text searched); newtontownshiplc.com home and Public Notices (June 2026); lickingcounty.gov/depts/planning/zoninginfo/newton.htm; county-hosted resolution (BlobID 49373); searches "Newton Township Licking County data center moratorium", "Newton Township Ohio trustees zoning"'),

('OH', 'Licking', 'Hartford township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.hartfordtownship.net/zoning',
 'The township''s zoning resolution (adopted 1999-11-21, amended 2005-10-16; full text reviewed) contains no data-centre or data-processing provisions and no moratorium language. Its 2026 special-meeting notices are routine (fair preparation, paving), and no news coverage of any Hartford trustee action on data centres was found.',
 '2026-09-12',
 'county-hosted Hartford Township Zoning Resolution (BlobID 49349, full text searched); hartfordtownship.net home and Meetings & Minutes page (2026 notices incl. Aug 1 special meeting); hartfordtownship.net resolutions folder; searches "Hartford Township Licking County data center", "Croton Ohio data center"'),

('OH', 'Licking', 'Licking township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.lickingtwplc.gov/zoning.aspx',
 'The township''s 2026 zoning resolution (109 pages, full text reviewed) contains no data-centre or data-processing provisions. Its only recent zoning change is a Mixed-Use Overlay District (Article 11, effective 2026-01-14) — a permissive planned-development overlay with no data-centre use listed or targeted. The township''s only Nov 3, 2026 ballot issue is a fire/EMS levy, not a data-centre measure.',
 '2026-09-12',
 'lickingtwplc.gov/zoning.aspx (township zoning notice; MUOD PDF dated 2025-10-29, full text searched); LickingTownshipZoningResolution_2026.pdf (full text searched); thereportingproject.org Nov 3 ballot-certification article (township issue = fire levy); searches "Licking Township Licking County data center moratorium"'),

('OH', 'Licking', 'Etna township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.etnatownship.com/35/Minutes',
 'No township-wide pause or ban. The township''s August 2026 "Harvey Farms Data Center Text Amendment" clarified that data centres are not a permitted use in General Business districts only — the ordinance continues to allow them in industrial and overlay districts (Trustee Rachel Zelazny: "The Township amended our zoning code to make it clear that data centers are not a permitted use in our General Business districts"; Newark Advocate, 2026-08-13: "Township ordinance allows data centers in industrial and overlay areas"). A district-level use-table fact, not a moratorium: GB districts already read prohibited in the county use-table mapping, so the amendment confirms the mapping rather than adding a restriction. The trustees'' exact adoption date is not yet posted (Zoning Commission hearing 2026-08-05; adoption reported by 2026-08-13).',
 '2026-09-12',
 'etnatownship.com Zoning Commission amended agenda 2026-08-05 (AgendaCenter: "Harvey Farms Data Center Text Amendment"); etnatownship.com Board of Trustees agenda 2026-08-18; etnatownship.com/35/Minutes; Newark Advocate 2026-08-13 "Etna Township adopts zoning changes amid interest from data center"; Trustee Rachel Zelazny public statements 2026-04-13 and 2026-08-13; searches "Etna Township Licking County data center moratorium", "Etna trustees adoption vote"'),

('OH', 'Licking', 'Jersey township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.jerseytownship.us/trustee-minutes-resolutions.html',
 'The township''s complete published trustees'' minutes (2022 - Aug 2026) and resolutions (2023 - Jul 2026) contain no moratorium, pause, or data-centre restriction — every land-use instrument is permissive (MCOD 2023-11-06, MUOD 2025-04-07, IE Subarea of WCOD and NEOD/NWIOD amendments 2025-07-23, Summit Rd PMUD, JEDDs, CRAs). The IE-W overlay expressly lists "Data Processing Centers" as a permitted use; an overlay that permits is not a restriction.',
 '2026-09-12',
 'jerseytownship.us/trustee-minutes-resolutions.html (minutes 2022-2026 and resolutions 2023-2026 reviewed item by item); jerseytownship.us/zoning-department.html; jerseytownship.us home; Resolution 24-10-07-01 (MUOD text-amendment initiation); lickingcounty.gov/depts/planning/zoninginfo/jersey.htm; searches "Jersey Township Licking County data center moratorium/restriction"'),

('OH', 'Licking', 'Newark township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://newarktwp.com/zoning',
 'The township''s official site has no minutes or notices section and its zoning page covers only permits and fees, with no text amendments, moratoria, or data-centre references. Its only Nov 3, 2026 ballot issue is a 1.5-mill road levy — no data-centre measure. News searches return only Newark city (charter-amendment petitions, a different jurisdiction) and St. Albans Township items, never the township trustees. Newark township is the unincorporated township, distinct from Newark city.',
 '2026-09-12',
 'newarktwp.com/zoning; newarktwp.com home and Township page; lickingcounty.gov/depts/planning/zoninginfo/newark.htm; thereportingproject.org Nov 3 ballot-certification article (township issue = road levy); searches "Newark Township Licking County data center moratorium" (all hits Newark city or St. Albans)');

-- ── Franklin County townships (15) ────────────────────────────────────────

INSERT INTO public.jurisdiction_restrictions
    (state_code, county_name, subdivision_name, status, instrument, adopting_body,
     adopted_date, effective_date, expires_date, scope, source_url, basis,
     reviewed_at, sources_checked)
VALUES
('OH', 'Franklin', 'Madison township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.madisontownship.org/board-meetings',
 'The township''s own records — 2025 archived minutes and every regular/special meeting record January-August 2026 plus the Township Express newsletters — contain no mention of data centres or a moratorium; the only data-centre-adjacent items are routine annexation notices (e.g. 167 acres on Winchester Pike annexed to Columbus, April 2026). Decoys rejected: every "Madison Township data center moratorium" news hit is Lake County (News-Herald), Butler County (WCPO/WVXU), or Madison County, Indiana.',
 '2026-09-12',
 'madisontownship.org/board-meetings; 2025-Archived-Minutes.pdf; minutes PDFs 2026-01-27, 02-24, 03-24, 04-28, 05-19, 06-23, 07-07; Express newsletters 2026-02-24, 07-28, 08-25; madisontownship.org zoning, news, home; searches "Madison Township Franklin County data center moratorium", "Madison Township Groveport data center proposal"'),

('OH', 'Franklin', 'Plain township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://plaintownship.org/',
 'No restriction traceable to Franklin County''s Plain Township (New Albany). Its official site''s news feed and a full site search for "data center" return only unrelated items (fire-station groundbreaking, invasive-plant program). Decoys rejected: the widely reported March 27, 2026 "Plain Township approves moratorium on data centers" (Canton Repository/Dispatch) is STARK County''s Plain Township, and the July 2026 "New Albany 1-year ban" stories (WLKY, Courier-Journal) are New Albany, INDIANA.',
 '2026-09-12',
 'plaintownship.org (home, news, site search "?s=data+center", zoning pages); Canton Repository/Dispatch 2026-03-27 moratorium article (verified Stark County); WLKY/Courier-Journal New Albany ban coverage (verified Indiana); searches "Plain Township New Albany data center moratorium", "plaintownship.org data center"'),

('OH', 'Franklin', 'Jefferson township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.jeffersontownship.org/government/agendas___minutes.php',
 'No adopted or pending data-centre land-use restriction found for Franklin County''s Jefferson Township (Blacklick). Its Civic Clerk agenda/minutes portal and news searches show no trustees action; the closest coverage (Spectrum News, 2026-03-20) describes the township weighing public-safety staffing pressures from nearby New Albany data-centre growth — not a restriction. Decoys rejected: the "Jefferson Twp data center amendment" and Amazon 590-acre purchase are Fayette County''s Jefferson Township.',
 '2026-09-12',
 'jeffersontownship.org/government/agendas___minutes.php; jeffersontownship.novusagenda.com indexed minutes; jeffersontwpoh.portal.civicclerk.com; Spectrum News 2026-03-20 "Growth raises safety concerns in Jefferson Township"; searches "Jefferson Township Franklin County data center", "Jefferson Township Blacklick trustees data center"'),

('OH', 'Franklin', 'Jackson township', 'adopted',
 'One-year moratorium on new data centre developments within the unincorporated portions of the township. The township''s own letter, verbatim: "On May 12, 2026, the Jackson Township Board of Trustees voted unanimously to enact a one-year moratorium on new data center developments within the unincorporated portions of our township."',
 'Jackson Township Board of Trustees (McClure, Mulvany, Rauck — unanimous)',
 '2026-05-12', '2026-05-12', '2027-05-12',
 'New data-centre development in unincorporated township territory only; the trustees'' letter notes township limits "do not control land once it is annexed into the city" (Grove City). The pause was framed for infrastructure (power/water), zoning-code updates, and resident concerns.',
 'https://jacksontwpfranklinoh.gov/cdn/Letter-to-the-Community-Data-Center.pdf',
 'Verified from the township''s own community letter signed by the Board, corroborated by the Columbus Dispatch (2026-05-13: "trustees have unanimously approved a 12-month moratorium... The May 12 vote"), 10TV, and ABC6 (the resolution "takes effect immediately and applies to unincorporated land"). expires_date is derived, not quoted: the letter states a one-year term from the 2026-05-12 adoption, so the row carries the arithmetic end 2027-05-12 and the gate will re-open by itself if no extension is recorded before then.',
 '2026-09-12',
 'jacksontwpfranklinoh.gov Letter-to-the-Community-Data-Center.pdf (township''s own record); Columbus Dispatch 2026-05-13 "Jackson Township imposes moratorium on data centers for a year"; 10TV 2026-05-12/13; ABC6/MyFox28 2026-05-13; NBC4 2026-05-14 Grove City coverage; jacksontwpfranklinoh.gov minutes'),

('OH', 'Franklin', 'Pleasant township', 'adopted',
 'Resolution 11 — the township''s own meeting highlights, verbatim: "Resolution 11 to put a moratorium on any building of data centers in Pleasant Township."',
 'Pleasant Township Board of Trustees',
 '2026-02-24', NULL, NULL,
 'Any building of data centres in Pleasant Township (unincorporated township territory); the same 2026-02-24 meeting heard a resident speaking "about annexation and the data centers asking for our support to stop them" — the trigger is the Rench Road data-centre proposal straddling the Grove City line.',
 'http://www.pleasanttownship.com/2026-meeting-minutes.html',
 'Verified from the township''s own 2026-02-24 meeting highlights, which list Resolution 11 verbatim; the vote is reported 2-1 by the Columbus Dispatch (2026-05-11: "trustees voted 2-1 on a data center moratorium in February"), and the Jackson Township trustees'' letter independently confirms Pleasant enacted a moratorium. No duration or end date appears anywhere in the township''s record, so expires_date stays NULL rather than inferred — the moratorium stands until the township says otherwise.',
 '2026-09-12',
 'pleasanttownship.com 2026-meeting-minutes page and 2/24/26 highlights (township''s own record); 2/10, 3/24, 4/14, 5/12/26 highlights; pleasanttownship.com resolutions page; Columbus Dispatch 2026-05-11 and 2026-05-13; ABC6/CW Columbus 2026-05-13; NBC4 coverage; searches on Pleasant Township moratorium duration'),

('OH', 'Franklin', 'Washington township', 'adopted',
 'Moratorium on construction or approval of data centres, later extended. Original motion (township minutes, verbatim): "Motion to Institute a 90-day Moratorium on Construction or Approval of Data Centers in Washington Township" (#2025.12.09.001). Extension (#2026.02.10.004, verbatim): "The Board hereby extends its large scale data center (Data Center Tiers 2-4) development moratorium six months, from March 9, 2026 to September 5, 2026."',
 'Washington Township Board of Trustees (Kranstuber, Harris, Rozanski)',
 '2025-12-09', '2025-12-09', '2026-09-05',
 'Unincorporated territory of the township; large-scale data centres (Tiers 2-4); construction or approval. While the pause runs, the township is drafting Zoning Resolution updates "to include, among other items, the prohibition of large-scale data centers," and formally urged the City of Dublin to refrain from approving further data centres.',
 'https://wtwpdublinoh.gov/cdn/2025.12.09-Minutes.pdf',
 'Verified from the township''s own adopted minutes: the moratorium was moved by Kranstuber, seconded by Harris, "Motion adopted December 9, 2025" (the Dispatch reported the vote as Dec 8 — the township''s own minutes control), and the 2026-02-10 resolution extended it to 2026-09-05. The Sept 8, 2026 agenda lists a further "Resolution Extending Data Center Development Moratorium," but its minutes were not yet posted, so the extension is unrecorded: as of a 2026-09-12 run the verified record has lapsed and the gate reads CONDITIONAL — the row surviving as the political-risk signal it is, to be re-dated when the minutes post.',
 '2026-09-12',
 'wtwpdublinoh.gov 2025.12.09-Minutes.pdf; 2026.01.13-Minutes.pdf; 2026.02.10-Minutes.pdf; 2026.03.10-Minutes.pdf; AGENDA-2026.09.08.pdf (extension listed, outcome unverified); wtwpdublinoh.gov meetings index; Columbus Dispatch 2025-12-15; ABC6 2025-12-15; Columbus Business First 2025-12-16; searches "Washington Township Franklin County data center moratorium" (Montgomery County OH and Macomb County MI items excluded)'),

('OH', 'Franklin', 'Hamilton township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.hamtwpfcoh.gov/',
 'No adopted or pending data-centre land-use restriction found for Franklin County''s Hamilton Township (Obetz/Canal Winchester area). Its official site contains no data-centre action or notice. Decoys rejected: every "Hamilton Township data center moratorium" result is a different jurisdiction — Warren County, Ohio (Maineville, Resolution 26-0520B), Lawrence County, Ohio, Butler County, or Atlantic City, New Jersey.',
 '2026-09-12',
 'hamtwpfcoh.gov (home, trustee-meetings, blog, homepage PDF); hamilton-township.org (verified Warren County, incl. Resolution 26-0520B); WOUB Lawrence County article; pressofatlanticcity.com NJ articles; searches "Hamilton Township Franklin County data center", "Hamilton Township Canal Winchester Obetz data center trustees"'),

('OH', 'Franklin', 'Mifflin township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://mifflin-oh.gov/',
 'Verified as Franklin County''s Mifflin (minutes headed "Mifflin Township Board of Trustees, Franklin County," OPS Center, 400 W Johnstown Rd, Gahanna). Full text of the 2026-05-04 and 2026-05-19 minutes packages (~200,000 characters including warrants, resolutions, agreements) contains zero occurrences of "data cent," "moratorium," or "zoning"; keyword extraction of the 2025-12-16, 2026-03-17 and 2026-08-03 minutes likewise found none; the township''s own site search returns no results. Decoys rejected: the widely covered 2026 "Mifflin" moratorium votes are Mifflin County, Pennsylvania, and a Mifflin Township in Richland County, Ohio.',
 '2026-09-12',
 'mifflin-oh.gov site search "?s=data center" and "?s=moratorium" (no results); full text of trustee minutes 2025-12-16, 2026-03-17, 2026-05-04, 2026-05-19, 2026-08-03; mifflin-oh.gov downloads archive; searches "Mifflin Township Franklin County Ohio data center moratorium", "site:mifflin-oh.gov data center"; ABC27/Data Center Dynamics Mifflin County PA coverage (excluded as wrong state)'),

('OH', 'Franklin', 'Sharon township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.sharontwp.us/',
 'Franklin County''s Sharon Township (Worthington) shows no data-centre restriction: its 2026 hearings cover only non-data-centre matters (tax budget and a JEDD amendment, pools-and-fences zoning amendments, the Walnut Ridge development plan). Decoys rejected: thesuntimesnews.com''s "Sharon Twp Resolution 2026-02-05-01" is Washtenaw County, MICHIGAN; a Medina County staff report is Sharon Center; WFMJ items are Sharon, Pennsylvania. Residual gap noted: an Aug 11, 2026 hearing on unspecified "proposed changes to the Sharon Township Zoning Resolution" could not be retrieved in full (page now 404); nothing links it to data centres.',
 '2026-09-12',
 'sharontwp.us "Public Hearing - Jul. 13", "Special Meeting - Jul. 21", zoning and home pages; sharontwp.org notices (Aug 11 and Sept 8, 2026 hearings, per indexed text); sharontwp.org news, zoning department, ZC and BZA 2026 schedules; searches "Sharon Township Franklin County Ohio data center moratorium"; Washtenaw County MI and Medina County OH Sharon items (excluded)'),

('OH', 'Franklin', 'Franklin township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://franklin-townshipohio.gov/',
 'This is the Franklin Township inside Franklin County ("one of four original Townships of Franklin County"). The township''s own site search returns no results for "data center" or "moratorium," and no news coverage names its trustees acting on data centres. Decoys rejected: the 2026 "Franklin Township data center" stories are Franklin Township, Richland County (525 Boyce Road proposal, April 2026 special meeting) and Franklin Township, Licking County (Brownsville moratorium push) — both excluded after location verification.',
 '2026-09-12',
 'franklin-townshipohio.gov site search "?s=data center" and "?s=moratorium" (no results); Mansfield News Journal 2026-04-15 Richland County article (excluded); Licking County Franklin Township items (excluded); searches "Franklin Township Franklin County Ohio data center moratorium", "ThisWeek Franklin Township Canal Winchester data center zoning"'),

('OH', 'Franklin', 'Truro township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://trurotwp.org/community-links/',
 'The township states on its own site: "Truro Township does not provide zoning services or issue building permits," deferring residents to the appropriate city/county offices — a township-level data-centre zoning action is structurally unlikely. Its site search returns nothing for "data" or "data center," its minutes and 2026 notices cover roads, cemetery and fire matters only, and no reputable news coverage names Truro trustees acting on data centres. Decoys rejected: the Provincetown Independent "Truro" zoning story is Truro, Massachusetts; the Athens "yearlong pause" story is Athens Township, Athens County.',
 '2026-09-12',
 'trurotwp.org (home, about, community-links zoning statement, meeting posts, 2025-10-02 minutes, site searches); searches "Truro Township Ohio data center moratorium trustees", "Truro Township zoning resolution data processing Blacklick"'),

('OH', 'Franklin', 'Blendon township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.blendontwp.org/government/board-of-trustees/resolutions/2026-resolutions',
 'Blendon Township OH''s own website (6350 S. Hempstead Road, Westerville) lists its complete 2026 resolutions (2026-01 through 2026-22): no moratorium or data-centre item — only appropriations, meeting dates, AEP opposition, wage scale, street parking, natural burial and similar matters. Decoy rejected: the June 15, 2026 "Blendon Township approves moratorium on data centers" coverage (MLive, Holland Sentinel) is Blendon Township, Ottawa County, MICHIGAN, confirmed by that township''s own June 15 agenda and mlive''s "Rural Ottawa County township" lede.',
 '2026-09-12',
 'blendontwp.org 2026 Resolutions page (complete list reviewed), zoning department and trustee zoning-hearings pages, home; blendontownship-mi.gov 2026-06-15 agenda and 2026-05-18 minutes (Michigan — excluded); MLive and Holland Sentinel 2026-06-15 articles (Michigan — excluded); searches "Blendon Township Ohio data center moratorium trustees"'),

('OH', 'Franklin', 'Perry township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'https://www.perrytwp.org/',
 'Franklin County''s Perry Township site shows no data-centre moratorium, restriction, or zoning text amendment; its search and current news feed yield nothing data-centre related. Decoys rejected: the heavily covered Perry Township data-centre fight (Panattoni proposal, "Township cannot place moratorium on data center," September 2026 transparency lawsuit) is Perry Township, STARK County (Massillon), and a further hit is Perry Township, Allen County (Lima) — both excluded after location verification.',
 '2026-09-12',
 'perrytwp.org site search and CivicAlerts news feed; Wikipedia "Perry Township, Franklin County, Ohio" (location confirmation); Canton Repository 2026-03-11 and ideastream 2026-09-03 Stark County coverage (excluded); perrytwp.com Stark County site (excluded); searches "Perry Township Groveport Ohio data center moratorium", "Perry Township Franklin County Ohio trustees data center zoning 2026"'),

('OH', 'Franklin', 'Norwich township', 'none_found', NULL, NULL, NULL, NULL, NULL, NULL,
 'http://norwichtownship.org/government/meetings___minutes/index.php',
 'The township hosts data centres — the Dispatch (2025-09-24) reports "In Norwich Township, which covers Hilliard, there are now three data center campuses, each operated by Amazon" — but no land-use restriction exists: no moratorium, pause, or data-processing zoning amendment appears in the township''s notices and minutes or in reputable news. Site searches for "data center" and "moratorium" on norwichtownship.org return nothing. Decoy rejected: the "data center ordinance" page at franklincountypa.gov is Franklin County, PENNSYLVANIA.',
 '2026-09-12',
 'norwichtownship.org (home, trustees, Meetings & Minutes pages, site searches "data center" and "moratorium" — no results); Columbus Dispatch 2025-09-24 "Jerome and Norwich township officials concerned with data center surge"; NBC4 2026-04-17 Hilliard-area energy-system story; franklincountypa.gov (PA — excluded); searches "Norwich Township Hilliard Ohio data center moratorium trustees"'),

('OH', 'Franklin', 'Prairie township', 'adopted',
 'Resolution No. 18-26 — verbatim title: "RESOLUTION TO ENACT A SIX-MONTH MORATORIUM ON THE RECEIPT, PROCESSING, ISSUANCE, OR APPROVAL OF ANY APPLICATION FOR A ZONING PERMIT FOR A DATA CENTER"',
 'Prairie Township Board of Trustees, Franklin County, Ohio (Stormont, Schmelzer)',
 '2026-04-15', '2026-04-15', '2026-10-15',
 'Suspends "the receipt, processing, issuance, or approval of any application for a Zoning Permit for a data center" township-wide. Carve-out (Section 2): "For Data Centers currently under construction, previously permitted, or demonstrating investment-backed expectations prior to the date of this Resolution, construction may proceed." Section 3 orders the Zoning Commission, planning consultants and legal counsel to study data-centre impacts and recommend text amendments — a "Data Center Analysis Report" was posted 2026-06-25 and zoning-resolution changes were still in process as of this review.',
 'https://www.prairietownship.org/DocumentCenter/View/9401',
 'Verified from the trustees'' own signed resolution on the township website, which names Prairie Township, Franklin County, Ohio and states it is "in full force and effect immediately upon its adoption" (2026-04-15), with the six-month term expiring 2026-10-15 ("The Board may rescind this moratorium at any time prior to the expiration of the six (6) months"). Corroborated by the Columbus Dispatch (2026-06-25: "Township trustees voted April 15 to enact a six-month data center development" pause, reported amid the Big Darby Accord land fight). The roll-call tally was not legible in the document text; adoption and its date are stated in the resolution itself.',
 '2026-09-12',
 'prairietownship.org Resolution 18-26 (DocumentCenter/View/9401, township''s own signed record); prairietownship.org News Flash "Data Center Analysis Report" 2026-06-25; "Prairie Township Zoning Resolution Changes - 070726" and proposed redline (View/9647); Zoning Commission public-hearing notices 2026-07-28 and 2026-09-22; Columbus Dispatch 2026-06-25; searches "Prairie Township Franklin County Ohio data center moratorium"');

-- ── Licking zoning use-table, third revision ──────────────────────────────
-- The brief's rule: a township that strikes a use from its table must have
-- that removal carried in its own scoped mapping, not decided by whichever
-- township wrote the flat entry. Harrison's M-1 never listed data centres
-- and its trustees struck the proposed addition on 2026-07-06 — the flat
-- M-1 by_right entry (supported by other townships' resolutions) must not
-- speak for Harrison. One scoped key; nothing else changes from
-- 2026-township-reviewed2.

WITH new_rule AS (
    INSERT INTO public.constraint_rules
        (gate_key, jurisdiction, rule_version, params, description,
         reviewed_at, reviewed_against)
    VALUES
    ('zoning_dc_use', 'Licking County, OH', '2026-township-reviewed3',
     $json${"by_right": ["M-1", "M-2", "I", "M&D"], "special_exception": ["PUD", "PMUD"], "prohibited": ["AG", "R", "R-1", "R-2", "R-3", "R-15", "R-45", "R-70", "R-87", "R-E", "RR", "RR-3", "RR-4", "RS", "SER", "ER-NEOD", "MHP", "PRCD", "CCRC", "B-1", "B-2", "GB", "GB1", "GB-1", "GB-2", "LB", "NB", "IB", "BLB", "JB", "AB", "CN"], "unknown_jurisdiction": ["UZ"], "district_classes": {"C-1|Granville": "prohibited", "C-1|Bennington": "prohibited", "C-1|Harrison": "prohibited", "C-1|Hartford": "prohibited", "C-1|Newark": "prohibited", "C-1|Madison": "prohibited", "C-1|Liberty": "prohibited", "M-1|Harrison": "prohibited"}, "overlay_classes": {"IE-W": "special_exception", "MCOA": "special_exception", "MCOB": "special_exception", "MU-W": "prohibited", "CPO-W": "prohibited", "MCOC": "prohibited", "MCOD": "prohibited", "HMU-NWIOD": "prohibited", "NMU-NWIOD": "prohibited", "MU-NEOD": "prohibited", "ER-NEOD": "prohibited"}, "standards_only_overlays": ["TC", "FP"], "standards_only_reasons": {"TC": "Liberty Twp. Zoning Resolution §811 (Transportation Corridor Overlay, amended eff. 12/18/2024): permitted uses are \"Any permitted use allowed in the underlying zoning district\" — corridor setback/access/screening/signage standards only", "FP": "Liberty Twp. Zoning Resolution §810 (Flood Plain Overlay): \"The base district shall determine uses and minimum requirements\" — floodplain development constraints, not a use table"}, "jurisdiction_reasons": {"UZ": "the township administers no zoning (the county layer marks it Unzoned); there is no use table to consult"}}$json$,
     'TOWNSHIP-REVIEWED USE TABLE, third revision (supersedes 2026-township-reviewed2, which decided the release18 run). Base districts, C-1 scoping, Jersey overlay classes, standards-only overlays and UZ are unchanged from that row — read its migration notes for those citations. THE CHANGE: Harrison Township''s trustees adopted zoning text amendments on 2026-07-06 (public hearing, 3-0 roll call: Van Buren YES, Smith YES, Foor YES) striking the Zoning Commission''s proposed addition of "Data Centers" as M-1 conditional use No. 18 (Article 16.2) and the proposed DATA CENTER / DATA CENTER CAMPUS definitions (Article 3) — minutes: harrisontownship.net/wp-content/uploads/2026/07/MINUTES-2026-07-06-Public-Hearing-Zoning-Amendments.pdf. Data centres are not a listed use in any district of the Harrison Township Zoning Resolution, so the flat M-1 by_right entry — supported by other townships'' resolutions — must not decide Harrison''s M-1: the scoped key "M-1|Harrison" reads prohibited (13 surveyed parcels). Harrison''s B-1, AG and R districts were already prohibited by the flat lists; its PUD parcels remain special_exception, the amendment not addressing planned developments. The same review confirmed Etna''s GB-district exclusion (August 2026 "Harvey Farms" text amendment) is already carried by the flat prohibited GB/GB1 entry — no change needed there.',
     '2026-09-12',
     'Harrison Township Board of Trustees public-hearing minutes 2026-07-06 (proposed M-1 conditional use "Data Centers" and DATA CENTER / DATA CENTER CAMPUS definitions struck before adoption); all other mappings unchanged from 2026-township-reviewed2')
    RETURNING id
)
UPDATE public.constraint_rules cr
SET superseded_by = (SELECT id FROM new_rule)
WHERE cr.jurisdiction = 'Licking County, OH'
  AND cr.gate_key = 'zoning_dc_use'
  AND cr.rule_version = '2026-township-reviewed2'
  AND cr.superseded_by IS NULL;

# D03-17A2b4a2 — source-backed main/header/footer reading and mapping

4 November2026. F05/F06/F08/F11. Follows completed b4a1 current reference proof (d028fb3, full5387 green), without closing
b3 complex table/native, paragraph joins, fields/notes/MC or full-DOCX gates. One bounded
function: read each potential section story once with original paths, hidden-text and
revision rules; source-backed batchmapping. No UI/ML/admission/DB/dependencies/export.

New namespace `src/ara/docx_analysis/visible_stories/`, two own acceptance modules
(test_docx_visible_stories.py/test_docx_visible_story_mapping.py), own edge tests,
contract/result/guide/queue. Exactly THREE old implementation files may change:
1. visible_main/_reader.py: protected part_name_for(source), body_for(root),
   root_properties(), section_properties(node) hooks; defaults extract exactly current
   main part/body/root checks and allowed sectionproperties. Constructor/plans delegate.
2. tables/_context.py: protected part_name_for/source and body_for/root hooks, same main
   defaults. Geometry/retained/current subclasses unchanged.
3. moves/_index.py: private markers/index keyword part_name/container. Defaults identical;
   supplied freshly validated storyroot changes only originalpart and expected ancestry
   (root/p for hdr/ftr, document/body/p for main). Pairing logic unchanged.
No other oldsource/tests/contracts/schema/tasks/runner changes. Freeze tests first; newly
written test setup corrections only documented without weaker assertions; review additions
before scripts/check.sh; selective local commits authorized.

Primary section/header/footer evidence in b4a1; Microsoft
[Header](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.header?view=openxml-3.0.1)
and [Footer](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.footer?view=openxml-3.0.1)
define hdr/ftr as root with paragraphs/tables. Not every valid OOXML child is supported
in this bounded reader; unsupported currentcontent remains blocked, never silently lost.

## Public API and identity

build_story_snapshot(data,*,document_id,storage_revision,source_sha256,limits=None),
map_story_spans/span same signatures and exact Visible DTO/VisibleLimits as existing
source-backed readers. Fixed `docx-analysis/final-visible-section-stories-v1`, same
policy final-visible-no-comments-v2. main_part remains actual package mainpart;
fragment.story_anchor is actual main body anchor or header/footer root path(). Flow
is body/storyroot or physicalcell; every atom/run/p anchor addresses originalpart/path.
No XML wrapping/copying/sourceDocxSource relabeling/stripping to fit oldmain grammar.
No caller-supplied catalog/styleproof/selectedpart becomes a capability.

Order main, then unique potential header/footer parts sorted together bycanonicalname.
No perpageorpersection copies, no crossstoryflow/joins and no pagecount/layoutclaim.
Default/first/even selections come ONLY from one freshly source-builtSectionCatalog;
parttext read only after matching kind/rootnamespace, with eachpart's ownrelationships.
Empty/inactive/orphanstory is not a requirement; actual disabledfirst/even definitions
may still inherit later accordingto b4a1. Unique sharedpart read once.

## Whole-source proof and bounds

Exact input/identity/bytes/sourcehash; archivesize beforehash; open_docx validates entire
originalZIP/XML. AggregateSAX preflight across main, allstyles MIME, selectedsettings,
ALLheader/footer MIME parts includinginactive/orphan, before anysemanticDOM. Count
nodes/depth/chars/namespaceURI/attrs plus storyparagraphs/runs/atoms against VisibleLimits.
Reuse revision/table and move counters across allstoryparts for their extra structural
caps, including excluded/historical payload. Styles-specific prepare_styles preflight
before SectionCatalog semanticparse; then one fresh read_section_catalog and one fresh
read_style_context per build. Section caps derived fromvisibleXMLlimits. No environment,
filesystem, DB,network, subprocess or ML imports during API/import.

Eachoriginalstorytree parsed boundedly after aggregatepreflight. New private storycontext
uses retained table recognition/GridGeometry over SAMEactualtree and partanchor; no
fake public maincatalog. Private fresh tableproof stores status,tables,histories,revisions;
private moveproof storesstatus,pairs from originalstory indexing. No externalproofinput.
For main only, proven SectionCatalog historyanchors are skipped by tablecontext so
old section/pPr payload cannot create currenttables. Existing whole-story move guard
remains conservative for markers hidden in historical/excluded branches. Crossstory
matching is forbidden; same move names in separate validstories are independent.

One original StyleContext for allstories, one cached table-styleproof when selected
byanytable, computed only againstthat exactfreshcontext. Existing paragraph/charhidden,
neutral table-style, current tablehistory/revisions, inferredgrid, continuationcontent,
hiddenrow and unresolved paragraphboundary guards reused. Tables in headers gettheir
own independent flows, selectors and originalsourceanchors; nested tables keeporder.

## Main section metadata and root grammar

StoryReader extends GridReader, protectedhooks choose original part and actual flowroot.
Main root defaults preserve oldrootchecks. Header/footer root must have correct hdr/ftr
and matching Wordnamespace, noattrs/textoutsidechildren; paragraph/tablegrammar isshared.
Closedunknownretainedbranches fail (SDT/MC/fields/notes/media remain othercycles).

CurrentsectPr accepted only if actualanchor matches freshSectionCatalog; header/footer
sectPr neverbecomes a mainsection. pPr/sectPr metadata accepted via same proof. Emit
section_properties and header_footer_reference metadata at actualanchors; previous
sectionhistory excluded at provedmarker, paragraphhistory remains existingevent.
Other listed sectionprops validateclosed nontext shapes before exclusion:
- leafWattrs type,pgSz,pgMar,paperSrc,lnNumType,pgNumType,formProt,vAlign,noEndnote,
  textDirection,bidi,rtlGutter,docGrid;
- cols: Wattrs + onlycol leafWattrs;
- pgBorders: Wattrs + uniquetop/left/bottom/right leafWattrs;
- footnotePr/endnotePr: noattrs + uniquepos/numFmt/numStart/numRestart leafWattrs.
No rawtext/foreignattrs/unknownnestedcontent silentlylost. titlePg/reference/history
are separatelyproved shapes. printerSettings stays blockedpending partaccounting.

## Package accounting, atomicity and mapping

Keep existing package metadata/comments policy/styleproof accounting. Exactselected
settings part becomes metadata section_settings_accounted. Every potentialstory must
be fully read before anyincludedfragments published. Unreferenced header/footer parts
get excluded/unreferenced_section_story only AFTER all active storygrammars AND main
sectionproof succeed; beforethat blocked/story_usage_unproven. Otherunknownparts still
blocked/unread_part (font/theme/numbering/etc needseparateproof). Known storyfailure,
sectioncatalogblocked, styleblocked or anyunreadpart makes whole new snapshot incomplete
with EMPTYfragments/analysis_text/paragraphs/runs. Neverpublish a trustworthy-looking
prefix or orphanexclusion when actualreferencecoverage is unresolved. Coverage has
partmetadata/explicitblockers, no includedfragmententry withoutcorrespondingfragment.

Success emits globalparagraph/runcontexts/fragments; textjoin twoLF only betweenfragments,
local offsets CodePoints and globalanalysisoffsets; allbudgets aggregate acrossstories.
Coverage/digests deterministic fromunchangedsource; text hidden inrepr/errors. Public
batchmap reuses shape/schema validators with fixednewprofile, one whole-original rebuild
(includingemptybatch), exactexpectedmanifest equality, thenexisting intervalmapping.
Rehashed foreigntext/parts/coverage/styles/anchors cannotbeaccepted; samequote different
stories remainsdifferent fragment/anchor, neversearchorcorrectoffsets.

## Acceptance/gate

StrictUTF16/customparts, sectioninheritance/order/dedupe; main+headerstable+footer text;
allsourcepaths/flow/bindingindependence; inactive/orphanunknowncontent excluded only
with fullreferenceproof; own hyperlinkrelationships; propertyhistories/retainedrevisions/
neutralstyles/hidden runs; independent inline move pairs andcrossstoryfailure;
closedmain/headerroots/sectionmetadata andbadpartfailureatomic; oldprofilesunchanged;
mapexactquotes/nonBMP/tabs/breaks, onceperbatch incl empty, forged/stale/profile/digest;
wholeXML+specific+manifest limits beforeDOM, noapplicationI/O; previous796files except
threehooks unchanged, fullcheck, readonlymainV8, result/guide/localcommit; continue.

# D03-17A2b4a1 — ordinary current sections and header/footer definitions

4 November2026. F05/F06/F11. Independent next b4a task; b3 grid/native hard cases
remain open, not removed from scope. This cycle implements a pure source reference
catalog, not text extraction, page layout, orphan exclusion or analysis admission.

Allowed new namespace `src/ara/docx_analysis/sections/`, acceptance
`tests/acceptance/test_docx_section_catalog.py`, own edge tests
`tests/docx_documents/test_section_catalog_edges.py`, this contract/result/guide/queue.
No oldsource/test/schema/dependency/runner/task/ML changes. Freeze before red; review
additions before final full gate. New setup corrections only documented if needed,
never weaken existing behavior assertions. Local selective commits authorized.

## Source semantics

[SectionProperties](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sectionproperties?view=openxml-3.0.1)
places ordinary boundaries at body/p/pPr/sectPr and final properties at endbody.
[HeaderReference](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.headerreference?view=openxml-3.0.1)
provides first/default/even definitions.
MS-OI29500 corrections for [headers](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/5de15e59-3ec1-4f80-aa4d-00bdd447b86f)
and [footers](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/02af532c-6791-4f63-b4b2-cd20e58dce91)
resolve obsolete SDK prose: missing default inherits previous default, not previous
even. Use real relationships URI including /relationships/ (strict equivalent too).
[titlePg correction](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/bce5f993-d683-4aa7-825e-bce25c64e8b8)
confirms first-page inheritance in later sections.
[TitlePage](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.titlepage?view=openxml-3.0.1)
and [EvenAndOddHeaders](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.evenandoddheaders?view=openxml-3.0.1)
are independent per-section/global flags; absent=false, empty=true, explicitfalse
supported. No actual page-count/pgNumType parity calculation; catalog lists potential
active variants, not rendered instances.
Official [ECMA376 part1 2016](https://ecma-international.org/publications-and-standards/standards/ecma-376/)
Strict XSD CT_SectPr/CT_HdrFtrRef inspected: <=6 references before sectionproperties,
required type/r:id, optional unique final sectPrChange. Historical sectPrBase cannot
supply current references. We preserve original history payload without activation.

## API and immutable records

`read_section_catalog(data, *, source_sha256, limits=None)`; exact bytes and lowercase
SHA256; archive bound before hash; open_docx validates package/relationships/DTD.
`SectionCatalogError` fixed codes invalid_input/source_mismatch/section_limit_exceeded.
`SectionLimits` frozen slots: max_xml_nodes100000, max_xml_depth128,
max_xml_characters8388608, max_sections4096, max_references24576,
max_histories20000, max_manifest_bytes33554432. All exactints1..default; reject foreign,
mutated/deleted-field limit instances. Aggregate whole-main + selected settings preflight
before any semantic DOM, including excluded histories, both Word namespaces and
namespaceURI/attrs/text. Count every sectPr/reference/history including opaque branches.
No dense pagesmatrix, recursion over inputtree, network/env/filesystem/applicationI/O.

Profile `docx-sections/current-header-footer-definitions-v1`.
SectionCatalog(source_sha256,profile,status,main_part,settings_part,even_and_odd,
sections,stories,histories,issues,catalog_sha256). Status indexed or blocked (at least
one implicit final section exists even without explicitsectPr). Blocked has empty
sections/stories/histories, even_and_odd=None. No complete/analysis_text capability.
Section(index,anchor optional,paragraph_anchor optional,first_page,references,bindings).
Reference(kind,variant,anchor,part_name). Binding(kind,variant,part_name optional,
definition_anchor optional,origin_section optional). Story(kind,part_name,root_anchor).
History(kind,anchor,owner_anchor,previous_anchor) for section/paragraph oldproperties.
Issue(code,anchor optional). SourceAnchor paths address actual originalelementnodes;
absent sectPr is None, implicitfinal section has no fake XML node. All sourceaddresses/
collections/partnames reprhidden; no copied text/author/date/r:id. Frozen slots allDTOs.
Canonical sortedcompact JSON digest excludescatalog_sha256, streaming bounded bytes.

## Recognition and relationships

Main root validateddocument/body. CurrentsectPr recognized ONLY directfinalbodychild,
or direct pPr of directbodyp (pPr uniquefirstchild; sectionproperty unique last before
optionalpPrChange). One finalsection appended with None whenbodysectPr absent; no inferred
properties inherited other than header/footerdefinitions. Wrongnamespace, duplicates,
misordering or relevant tags in unrecognizedparent blocked, never pickedup bylocalname.
Bodyp boundaries with current mark ins/del/moveFrom/moveTo are unresolved_section_revision;
no guessing final section topology. Cell/wrapped sections similarly unsupportedcontext.
Section attributes only rsidR/rsidRPr/rsidSect/rsidDel 8hex; whitespacecontainers.
Allowed other directsectionproperties: footnotePr,endnotePr,type,pgSz,pgMar,paperSrc,
pgBorders,lnNumType,pgNumType,cols,formProt,vAlign,noEndnote,textDirection,bidi,rtlGutter,
docGrid,printerSettings (unique, sameNS). Kept as metadata only; no layout validityclaim.
Any relevant reference/section/titleflag hiddeninside these orotherwrappers blocks.

CurrenttitlePg exactleaf/optionalval boolean 1/0,true/false,on/off, nootherattrs.
Reference exactleaf requiredsameWordNS type(first/default/even) andmatchingstrict/trans
r:id, unique(kind,variant) <=6, beforeothersectionprops. Resolve by actualmainrelationship
ID, exactmatchinginternal header/footer relationshipkind + MIME; external/missing/wrong
kind/wrongMIME blocked, neverfetch. Header/footer XML text is not read here. Unreferenced
orphanparts not included as stories but NOT classified safe-to-ignore.

Settings: no settingsMIME/relationship ->false; otherwise exactlyonepart ofsettingsMIME
and exactlyonemainsettingsrelationship internal matchingtarget. Ambiguous/external/
orphan/wrongMIME ->unresolved_section_settings. Read originalsettingsroot sameWordNS;
one direct evenAndOddHeaders exactbooleanleaf. Misplaced/foreign/duplicateflag blocked.
Other settings are not interpreted as documenttext; nestedflag cannot silently win.

History excluded only direct sectPrChange of actualcurrentsectPr or pPrChange of actual
bodyp/pPr, unique lastmarker, requiredsigneddecimalid <=20digits, optionalauthor/date,
whitespacecontainer, exactone sameNS previousroot, previousrootattrsnone (sectPr allows
samevalidatedrsidattrs). Recordoriginalanchors; do not interpret descendants. Historical
sectPr/refs never become currentsections or enable stories; preflightstillcountsall.
Malformed/historywrongcontext relevantnodes block. Other historicalcontexts/complex
sectionrevision behavior remain unsupportedexplicitly, not flattened.

## Inheritance and potential stories

Walk currentsections in originalorder. Carry each(kind,variant) definition independently;
local reference replaces only thatslot even if variantinactive in thissection. Emit
bindings in header thenfooter order, each default,first(if titlePg),even(if globalflag).
Missing first-section definition is blank(None), never fallbacktoanother variant.
Inheritance records actualoriginsection/referenceanchor, not phantomlocalreference.
Unique nonblank potentialstories sorted bycanonicalpartname (bothkinds together),
rootanchor sourcepart path(). Samepartmultiplebindings read once downstream. Current
catalog does not validate storyroots/content nor authorize body/unknownbranch/orphan
exclusion; fresh compatible storyreader plus coverage required nextcycle.

## Acceptance and gate

Synthetic strictUTF16/customparts; explicit+implicitsections; exactanchors; defaults,
first/even on/off, inactivefirstdefinition inheritedlater, no crossvariantfallthrough,
sharedpartdedupe; historicalreferences excluded; wrongcontext/namespace/order/duplicates,
invalid/externalrelationships and settings; failureatomic goodprefix thenbad;
exact input/caps/streamingmanifest and allbranches beforeDOM; immutable/repr/noI/O;
alloldtestsunchanged, targeted+regression, scripts/check.sh, previous787hashesunchanged,
readonlymainV8 snapshot, result/guide/localcommit; continue autonomously.

# Spike S2 results: Tavily as evidence source for the resolver

Run: 2026-09-16 21:05. Tavily CLI, basic depth, top 5. 38 searches in 137 s.

## A. Misspelled products (G2 dev variants)

Hit = the correct ONSSA trade name appears in a top-5 result.

| Written | Correct | Kind | `web`: name + pesticide Maroc (country=morocco) | `fr`: name + produit phytosanitaire homologué ONSSA |
|---|---|---|---|---|
| BARKLAY BARBARIAN SUPER 360 | BARCLAY BARBARIAN SUPER 360 | c_k_swap | #1 www.marocagriculture.com/index-phytosanitaire | #1 fallah365.com/fr/matieres-actives/glyphosate- |
| CR0NOS | CRONOS | o_zero_swap | miss (5 results) | miss (5 results) |
| KATANGA TR1PLE | KATANGA TRIPLE | o_zero_swap | #1 www.marocagriculture.com/index-phytosanitaire | #1 eservice.onssa.gov.ma/IndPesticide.aspx |
| KUIVREVAL 20 WG | CUIVREVAL 20 WG | c_k_swap | #1 www.marocagriculture.com/index-phytosanitaire | miss (5 results) |
| SOUPYTO | SOUPHYTO | letter_dropped | miss (5 results) | miss (5 results) |
| VELUM PR1ME | VELUM PRIME | o_zero_swap | #1 futurecrops.ma/nematicides/179-velum-prime.ht | #1 hygo.ag/fr/ressources/catalogue-hygolex/produ |
| ZOXYBIN | ZOXYBIN 25 SC | formulation_dropped | #1 www.agrimaroc.ma/pesticides-maroc | miss (5 results) |

Correct name surfaced by at least one strategy: **5/7** (web 5, fr 3).

## B. Label substance names the deterministic resolver cannot map (G2s seed)

Hit = a top-5 result contains evidence of the EU identity. `echo` = the evidence word is already in the query, so a hit proves little.

| Label name | EU substance | `fr` query | `en` query |
|---|---|---|---|
| (E,E) 8,10-dodécadien-1-ol | (E,E)-8,10-Dodecadien-1-ol (SCLP Alcohols) | #1 ec.europa.eu/food/plant/pesticides/eu-pestici | #1 www.thegoodscentscompany.com/data/rw1057941.h |
| 1-Dodecanol | Dodecan-1-ol (SCLP Alcohols) | #1 www.sagepesticides.qc.ca/Recherche/RechercheM | miss (5 results) |
| 1-Tetradecanol | Tetradecan-1-ol (SCLP Alcohols) | #1 pubchem.ncbi.nlm.nih.gov/compound/1-Tetradeca | #1 pubchem.ncbi.nlm.nih.gov/compound/1-Tetradeca |
| Cuivre - oxychlorure de cuivre | Copper oxychloride | miss (5 results) | #1 www.bcpcpesticidecompendium.org/copper%20oxyc |
| Cuivre - sulfate de cuivre | Copper compounds | miss (5 results) | #1 npic.orst.edu/factsheets/archive/cuso4tech.ht |
| Cuivre - sulfate tétracuivrique tricalcique | Bordeaux mixture | #3 npic.orst.edu/factsheets/archive/cuso4tech.ht | #1 npic.orst.edu/factsheets/archive/cuso4tech.ht |
| Fosétyl-Aluminium | Fosetyl | #1 sitem.herts.ac.uk/aeru/iupac/Reports/363.htm (echo) | #1 www.echemportal.org/echemportal/substance-sea (echo) |
| Glyphosate -sel d'isopropylamine | Glyphosate | #1 www.facebook.com/sani.ahmad.1232/posts/glypha | #2 en.wikipedia.org/wiki/Roundup_(herbicide) |
| Huile minérale paraffinique | Paraffin oil | miss (5 results) | #1 pmc.ncbi.nlm.nih.gov/articles/PMC11263917 |
| Hydrolysat de protéines | Hydrolysed proteins | #2 efsa.onlinelibrary.wiley.com/doi/10.2903/j.ef | #1 efsa.onlinelibrary.wiley.com/doi/10.2903/j.ef |
| Propamocarbe HCl | Propamocarb | #1 archive.epa.gov/pesticides/reregistration/web | #3 archive.epa.gov/pesticides/reregistration/web |
| Pyrèthre | Pyrethrins | #5 npic.orst.edu/factsheets/pyrethrins.html | #1 citybugs.tamu.edu/factsheets/ipm/ent-6003 |

Evidence found by at least one strategy: **12/12**; excluding cases where both queries echo the evidence: 11/11.

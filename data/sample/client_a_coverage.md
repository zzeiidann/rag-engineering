# client a coverage
Client A outpatient coverage limit is IDR 5,000,000 annually. Contract A-CONTRACT covers specialist consultations. Dental implants are excluded.
@entity main|Contract|Client A contract coverage
@entity detail|Benefit|Outpatient specialist consultations
@edge main|COVERS|detail
@entity limit|CoverageLimit|IDR 5,000,000 outpatient coverage limit
@entity exclusion|Exclusion|Dental implants
@edge main|HAS_LIMIT|limit
@edge main|EXCLUDES|exclusion

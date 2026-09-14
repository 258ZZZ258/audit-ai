"""监督资料接收和证据提取契约；不承担上传、权限或任务状态。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Identifier = Annotated[Text, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")]
Section = Literal[
    "external.regulatory",
    "external.audit",
    "internal.audit",
    "internal.compliance",
    "internal.risk",
    "internal.accountability",
    "internal.daily.compliance",
    "internal.daily.risk",
    "internal.daily.litigation",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UploadMetadata(Contract):
    documentId: Identifier
    documentVersionId: Identifier
    fileName: Text
    title: str | None = None
    issueDate: str | None = None
    categoryCode: Text
    documentOrigin: Literal["internal", "external"]
    organizationIds: list[Text] = Field(min_length=1)
    uploadEntry: Literal["file-center", "supervision"]


class Organization(Contract):
    organizationId: Text
    name: Text
    aliases: list[Text] = Field(default_factory=list)


class ExtractionField(Contract):
    key: Text
    description: Text
    required: bool = False


class ExtractionRule(Contract):
    ruleId: Text
    reportSection: Section
    extractFields: list[ExtractionField] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_fields(self):
        keys = [f.key for f in self.extractFields]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate extraction field")
        return self


class SupervisionExtractRequest(Contract):
    metadata: UploadMetadata
    organizations: list[Organization] = Field(min_length=1)
    rules: list[ExtractionRule] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_scope(self):
        orgs = [o.organizationId for o in self.organizations]
        rule_ids = [r.ruleId for r in self.rules]
        if len(orgs) != len(set(orgs)) or set(orgs) != set(self.metadata.organizationIds):
            raise ValueError("organization directory must match uploaded organizationIds exactly")
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("duplicate ruleId")
        return self


class SupervisionEvidence(Contract):
    evidenceId: str
    documentId: str
    documentVersionId: str
    locatorType: Literal["PARAGRAPH", "TABLE_ROW", "PAGE_TEXT"]
    locatorValue: str
    pageStart: int | None
    pageEnd: int | None
    text: str


class EvidenceCitation(Contract):
    evidenceId: Text
    quote: Text


class ExtractedValue(EvidenceCitation):
    value: Text
    supportingEvidence: list[EvidenceCitation] = Field(default_factory=list)

    def citations(self) -> list[EvidenceCitation]:
        return [
            EvidenceCitation(evidenceId=self.evidenceId, quote=self.quote),
            *self.supportingEvidence,
        ]


class FactCandidate(Contract):
    ruleId: Text
    factType: Literal[
        "FINDING", "RECTIFICATION", "ACCOUNTABILITY", "LITIGATION", "UNSPECIFIED"
    ] = "UNSPECIFIED"
    organizationIds: list[Text] = Field(min_length=1)
    values: dict[str, ExtractedValue] = Field(min_length=1)


class ModelFacts(Contract):
    facts: list[FactCandidate]

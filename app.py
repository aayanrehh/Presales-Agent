from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import streamlit as st
from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils import generate_presentation_slides, generate_word_document


APP_DIR = Path(__file__).resolve().parent
ENGINE_DIR = APP_DIR / ".engine_knowledge"
TEMPLATE_DIR = ENGINE_DIR / "templates"
LOG_PATH = APP_DIR / "app.log"
AGENT_FILES = {
    "orchestrator": ENGINE_DIR / "skill.md",
    "rfp": ENGINE_DIR / "agent_rfp.md",
    "raid": ENGINE_DIR / "agent_raid.md",
    "qa": ENGINE_DIR / "agent_qa.md",
}
TEMPLATE_FILES = {
    "scope": TEMPLATE_DIR / "scope_template.md",
    "raid": TEMPLATE_DIR / "raid_template.md",
    "qa": TEMPLATE_DIR / "qa_template.md",
}
MAX_UPLOAD_FILES = 5


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("presales_agent")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
    return logger


LOGGER = configure_logging()


class ImpactSeverity(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class PipelinePhase(str, Enum):
    INGESTION = "Ingestion"
    STRUCTURAL_EXTRACTION = "Structural Extraction"
    TABULAR_MAPPING = "Tabular Mapping"
    DOCUMENT_COMPILATION = "Document Compilation"


class DocumentStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    words: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    completeness_score: int = Field(ge=0, le=100)


class Deadline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestone: str = Field(min_length=3)
    timeframe: str = Field(min_length=2)
    business_value: str = Field(min_length=8)


class ScopeRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = Field(min_length=24)
    objectives: list[str] = Field(min_length=1)
    deliverables: list[str] = Field(min_length=1)
    core_constraints: list[str] = Field(min_length=1)
    chronological_deadlines: list[Deadline] = Field(min_length=1)
    functional_checklist: list[str] = Field(min_length=1)

    @field_validator("objectives", "deliverables", "core_constraints", "functional_checklist")
    @classmethod
    def reject_blank_items(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item and item.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty item is required.")
        return cleaned


class RiskItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    risk_factor: str = Field(alias="Risk Factor", min_length=8)
    category: str = Field(alias="Category", min_length=3)
    impact_severity: ImpactSeverity = Field(alias="Impact Severity")
    proactive_mitigation_strategy: str = Field(alias="Proactive Mitigation Strategy", min_length=12)


class RiskRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raid_risk_matrix: list[RiskItem] = Field(min_length=1)


class StaffingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=3)
    allocation: str = Field(min_length=2)
    responsibility: str = Field(min_length=8)


class QAIntelligence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommended_testing_stack: str = Field(min_length=8)
    testing_strategy: list[str] = Field(min_length=1)
    tooling_frameworks: list[str] = Field(min_length=1)
    staffing_matrix: list[StaffingItem] = Field(min_length=1)
    staffing_allocation_index: float = Field(ge=0.1, le=20)


class PresalesAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_requirements: ScopeRequirements
    raid_risk_matrix: list[RiskItem] = Field(min_length=1)
    qa_intelligence: QAIntelligence
    generated_at: str
    source_mode: Literal["local", "mock"]
    validation_trace: list[str] = Field(default_factory=list)


class PipelineFailure(Exception):
    def __init__(self, phase: PipelinePhase, message: str, original: Exception | None = None) -> None:
        self.phase = phase
        self.original = original
        super().__init__(message)


MOCK_ANALYSIS = PresalesAnalysis(
    scope_requirements=ScopeRequirements(
        executive_summary=(
            "A phased enterprise migration from a legacy data-center estate into a secure hybrid cloud operating "
            "model, prioritizing customer-facing workload continuity, governed data movement, zero-trust access "
            "controls, and measurable reduction in infrastructure run-rate."
        ),
        objectives=[
            "Inventory and classify 140 legacy applications across business criticality, data sensitivity, and integration depth.",
            "Migrate tier-2 reporting, integration, and partner-facing services before tier-1 transactional systems.",
            "Establish landing zones with segmented networking, centralized observability, policy-as-code, and audited CI/CD gates.",
            "Retire redundant middleware and batch processing nodes after validated performance parity and rollback readiness.",
        ],
        deliverables=[
            "Cloud readiness assessment and dependency heatmap.",
            "Reference architecture for secure landing zones and workload migration waves.",
            "Migration factory backlog with acceptance criteria, cutover plan, and rollback playbooks.",
            "Operational handover package covering monitoring, incident response, cost controls, and service ownership.",
        ],
        core_constraints=[
            "No customer-facing outage longer than 30 minutes during regional cutovers.",
            "PCI-scoped datasets must remain encrypted in transit and at rest with customer-managed keys.",
            "Legacy Oracle reporting interfaces must be supported until the final data warehouse transition.",
            "All production releases require automated regression evidence and change advisory sign-off.",
        ],
        chronological_deadlines=[
            Deadline(
                milestone="Discovery and application rationalization",
                timeframe="Weeks 1-3",
                business_value="Confirms scope boundaries, dependency risks, and migration sequencing before build spend.",
            ),
            Deadline(
                milestone="Landing zone and compliance foundation",
                timeframe="Weeks 4-7",
                business_value="Creates secure, repeatable deployment patterns for regulated workloads.",
            ),
            Deadline(
                milestone="Pilot migration wave",
                timeframe="Weeks 8-12",
                business_value="Proves cutover, rollback, monitoring, and stakeholder acceptance on low-risk systems.",
            ),
            Deadline(
                milestone="Business-critical migration waves",
                timeframe="Weeks 13-24",
                business_value="Moves revenue-adjacent applications while preserving operational continuity.",
            ),
        ],
        functional_checklist=[
            "Define application grouping, ownership, and RTO/RPO targets.",
            "Validate identity federation, privileged access, and environment segregation.",
            "Automate infrastructure provisioning with policy checks and security scanning.",
            "Build synthetic monitoring and transaction-level alerting for migrated services.",
            "Document rollback procedures, data reconciliation, and change approvals for each wave.",
        ],
    ),
    raid_risk_matrix=[
        RiskItem(
            **{
                "Risk Factor": "Undocumented point-to-point integrations create hidden cutover dependencies.",
                "Category": "Dependency",
                "Impact Severity": "High",
                "Proactive Mitigation Strategy": "Run interface discovery workshops, dependency tracing, and contract testing before each wave freeze.",
            }
        ),
        RiskItem(
            **{
                "Risk Factor": "Data residency controls are inconsistently mapped across analytics workloads.",
                "Category": "Compliance",
                "Impact Severity": "High",
                "Proactive Mitigation Strategy": "Tag datasets by jurisdiction, enforce policy-as-code guardrails, and obtain compliance approval before migration.",
            }
        ),
        RiskItem(
            **{
                "Risk Factor": "Legacy batch windows may exceed the cloud target operating window.",
                "Category": "Performance",
                "Impact Severity": "Medium",
                "Proactive Mitigation Strategy": "Benchmark representative workloads, tune compute profiles, and redesign high-volume jobs into parallelized pipelines.",
            }
        ),
        RiskItem(
            **{
                "Risk Factor": "Cost growth from over-provisioned non-production environments.",
                "Category": "Financial",
                "Impact Severity": "Medium",
                "Proactive Mitigation Strategy": "Apply budgets, schedules, rightsizing reports, and owner-level chargeback dashboards from the first sprint.",
            }
        ),
    ],
    qa_intelligence=QAIntelligence(
        recommended_testing_stack="Regression coverage + API validation + integration checks + performance smoke testing",
        testing_strategy=[
            "Build API contract suites for migrated services and legacy integration adapters.",
            "Run smoke journeys against customer-critical workflows before and after cutover.",
            "Compare baseline latency, error rates, and throughput by migration wave.",
            "Automate data reconciliation checks for migrated tables, file transfers, and reporting extracts.",
            "Gate production releases with regression evidence, vulnerability scan results, and rollback validation.",
        ],
        tooling_frameworks=[
            "Regression test suite",
            "API validation checklist",
            "Data reconciliation controls",
            "Performance smoke tests",
            "Release readiness checklist",
        ],
        staffing_matrix=[
            StaffingItem(
                role="QA Architect",
                allocation="1 FTE",
                responsibility="Owns test strategy, release gates, risk-based coverage, and QA governance.",
            ),
            StaffingItem(
                role="Test Automation Engineers",
                allocation="2 FTE",
                responsibility="Build API, UI, and regression automation integrated into CI/CD.",
            ),
            StaffingItem(
                role="Performance Engineer",
                allocation="0.5 FTE",
                responsibility="Models workload baselines, executes load tests, and validates tuning outcomes.",
            ),
            StaffingItem(
                role="Security QA Specialist",
                allocation="0.5 FTE",
                responsibility="Coordinates DAST, dependency scanning, access-control testing, and evidence capture.",
            ),
        ],
        staffing_allocation_index=4.0,
    ),
    generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    source_mode="mock",
    validation_trace=[
        "Ingestion validated",
        "Structural Extraction validated",
        "Tabular Mapping validated",
        "Document Compilation validated",
    ],
)


def configure_page() -> None:
    st.set_page_config(
        page_title="AI Delivery & Presales Assistant",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()


def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

        :root {
            --bg: #0B0D10;
            --panel: rgba(22, 27, 34, 0.45);
            --panel-solid: #161B22;
            --metal: #1F242E;
            --border: rgba(255, 255, 255, 0.08);
            --text: #F8FAFC;
            --muted: #AEB7C4;
            --silver: #D8DEE9;
            --emerald: #2ECC71;
            --emerald-soft: rgba(46, 204, 113, 0.4);
            --amber: #F2B84B;
            --red: #FF6B6B;
        }

        html, body, [data-testid="stAppViewContainer"], .stApp {
            background: #0B0D10 !important;
            color: var(--text);
            font-family: 'Plus Jakarta Sans', sans-serif !important;
        }

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        #MainMenu,
        footer {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
        }

        .stApp {
            background:
                radial-gradient(circle at 15% 0%, rgba(46, 204, 113, 0.09), transparent 26%),
                radial-gradient(circle at 85% 8%, rgba(216, 222, 233, 0.045), transparent 28%),
                linear-gradient(180deg, #0B0D10 0%, #0E1117 52%, #0B0D10 100%) !important;
        }

        h1, h2, h3, h4, h5, h6,
        p, li, label, button, input, textarea,
        [data-testid="stMarkdownContainer"],
        [data-testid="stWidgetLabel"],
        [data-testid="stCaptionContainer"],
        [data-testid="stMetric"] {
            font-family: 'Plus Jakarta Sans', sans-serif !important;
        }

        .material-icons,
        .material-symbols-rounded,
        .material-symbols-outlined,
        span[translate="no"],
        [data-testid="stIconMaterial"] {
            font-family: 'Material Symbols Rounded', 'Material Icons' !important;
            font-feature-settings: 'liga' !important;
            letter-spacing: normal !important;
            text-transform: none !important;
        }

        .ux-intake-card,
        .ux-upload-card {
            display: none !important;
        }

        [data-testid="stSidebarCollapseButton"],
        [data-testid="stFileUploader"] [data-testid="stIconMaterial"] {
            display: none !important;
            visibility: hidden !important;
        }

        [data-testid="stSidebar"] {
            background: rgba(11, 13, 16, 0.86) !important;
            border-right: 1px solid rgba(255, 255, 255, 0.07);
            backdrop-filter: blur(18px);
        }

        [data-testid="stSidebar"] * {
            color: var(--silver);
        }

        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 3rem;
            max-width: 1480px;
        }

        h1, h2, h3 {
            color: var(--text);
            letter-spacing: 0;
            font-weight: 800;
        }

        p, li, label, .stMarkdown, [data-testid="stCaptionContainer"] {
            color: var(--muted);
        }

        .hero {
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            padding: 1.45rem 1.55rem;
            background: linear-gradient(135deg, rgba(22, 27, 34, 0.56), rgba(11, 13, 16, 0.74));
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            backdrop-filter: blur(12px);
            margin-bottom: 1rem;
        }

        .hero-title {
            color: var(--text);
            font-size: 2.25rem;
            line-height: 1.08;
            font-weight: 800;
            margin: 0;
        }

        .hero-subtitle {
            color: var(--muted);
            font-size: 1rem;
            margin-top: 0.6rem;
            max-width: 1040px;
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            border: 1px solid rgba(46, 204, 113, 0.42);
            color: #BDF7D4;
            padding: 0.36rem 0.7rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            background: rgba(46, 204, 113, 0.08);
            box-shadow: inset 0 0 20px rgba(46, 204, 113, 0.04);
        }

        [data-testid="stVerticalBlockBorderWrapper"]:has(.ux-intake-card),
        [data-testid="stVerticalBlockBorderWrapper"]:has(.ux-upload-card) {
            background: rgba(22, 27, 34, 0.45) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 16px !important;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37) !important;
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            padding: 1.15rem !important;
        }

        div[data-testid="stMetric"] {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.9rem;
            min-height: 4.25rem;
            background: linear-gradient(135deg, rgba(31, 36, 46, 0.42), rgba(22, 27, 34, 0.30)) !important;
            border: 1px solid rgba(216, 222, 233, 0.14) !important;
            border-radius: 999px !important;
            padding: 0.78rem 1.05rem !important;
            box-shadow: 0 0 24px rgba(46, 204, 113, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
            backdrop-filter: blur(10px);
        }

        div[data-testid="stMetric"] label {
            color: #AEB7C4 !important;
            font-size: 0.72rem !important;
            font-weight: 800 !important;
            letter-spacing: 0.12em !important;
            text-transform: uppercase !important;
        }

        div[data-testid="stMetricValue"] {
            color: #F8FAFC !important;
            font-size: 1.55rem !important;
            font-weight: 800 !important;
        }

        textarea, input {
            color: var(--text) !important;
            background: rgba(11, 13, 16, 0.55) !important;
            border: 1px solid rgba(255, 255, 255, 0.10) !important;
            border-radius: 14px !important;
            box-shadow: none !important;
            transition: border-color 180ms ease, box-shadow 180ms ease, background 180ms ease !important;
        }

        textarea::placeholder, input::placeholder {
            color: rgba(216, 222, 233, 0.46) !important;
            opacity: 1 !important;
        }

        textarea:focus, input:focus,
        textarea:focus-visible, input:focus-visible,
        div[data-baseweb="textarea"]:focus-within,
        div[data-baseweb="input"]:focus-within {
            border-color: rgba(46, 204, 113, 0.62) !important;
            box-shadow: 0 0 0 1px rgba(46, 204, 113, 0.22), 0 0 18px rgba(46, 204, 113, 0.16) !important;
            outline: none !important;
            background: rgba(11, 13, 16, 0.72) !important;
        }

        div[data-baseweb="textarea"], div[data-baseweb="input"] {
            border-color: transparent !important;
            background: transparent !important;
            box-shadow: none !important;
        }

        .stButton > button[kind="primary"],
        .stDownloadButton > button {
            border-radius: 14px !important;
            border: 1px solid rgba(46, 204, 113, 0.72) !important;
            background: linear-gradient(135deg, #1F242E 0%, #161B22 100%) !important;
            color: #F8FAFC !important;
            font-weight: 800 !important;
            letter-spacing: 0.13em !important;
            text-transform: uppercase !important;
            min-height: 3.25rem !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 10px 26px rgba(0, 0, 0, 0.28) !important;
            transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease !important;
        }

        .stButton > button[kind="primary"]:hover,
        .stDownloadButton > button:hover {
            border-color: rgba(46, 204, 113, 1) !important;
            color: #FFFFFF !important;
            box-shadow: 0 0 20px rgba(46, 204, 113, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
            transform: translateY(-1px);
        }

        .stButton > button[kind="primary"]:active,
        .stDownloadButton > button:active {
            transform: translateY(0);
        }

        [data-testid="stFileUploader"] section {
            background: rgba(15, 23, 42, 0.56) !important;
            border: 1px dashed rgba(148, 163, 184, 0.28) !important;
            border-radius: 14px !important;
            padding: 1rem !important;
        }

        [data-testid="stFileUploader"] button {
            background: rgba(15, 23, 42, 0.92) !important;
            border: 1px solid rgba(148, 163, 184, 0.32) !important;
            border-radius: 10px !important;
            color: #E5E7EB !important;
            font-weight: 700 !important;
            letter-spacing: 0 !important;
            text-transform: none !important;
            box-shadow: none !important;
            min-height: 2.5rem !important;
        }

        [data-testid="stFileUploader"] button:hover {
            border-color: rgba(46, 204, 113, 0.58) !important;
            box-shadow: 0 0 12px rgba(46, 204, 113, 0.16) !important;
            transform: none !important;
        }

        .guidance-panel, .output-shell, .mini-card {
            border: 1px solid rgba(255, 255, 255, 0.08);
            background: rgba(22, 27, 34, 0.45);
            border-radius: 16px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.25);
            backdrop-filter: blur(12px);
        }

        .guidance-panel, .output-shell {
            padding: 1.05rem 1.1rem;
            margin: 0.75rem 0;
        }

        .mini-card {
            padding: 1rem;
            min-height: 118px;
        }

        .mini-card h4 {
            color: var(--text);
            margin: 0 0 0.45rem 0;
            font-size: 1rem;
        }

        .mini-card p {
            color: var(--muted);
            margin: 0;
            line-height: 1.45;
        }

        .signal-good { color: var(--emerald); font-weight: 800; }
        .signal-warn { color: var(--amber); font-weight: 800; }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.35rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }

        .stTabs [data-baseweb="tab"] {
            background: rgba(22, 27, 34, 0.55);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px 14px 0 0;
            color: var(--silver);
            padding: 0.75rem 1rem;
        }

        .stTabs [aria-selected="true"] {
            color: var(--text);
            background: rgba(31, 36, 46, 0.78);
            border-top: 1px solid rgba(46, 204, 113, 0.8);
            box-shadow: 0 -8px 22px rgba(46, 204, 113, 0.08);
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.23);
        }

        .ux-section-kicker {
            color: #BDF7D4;
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin: 1.3rem 0 0.45rem;
        }

        .workflow-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.9rem;
            margin: 0.9rem 0 1.05rem;
        }

        .workflow-card {
            position: relative;
            overflow: hidden;
            min-height: 118px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 1rem;
            background:
                linear-gradient(135deg, rgba(22, 27, 34, 0.62), rgba(11, 13, 16, 0.74)),
                radial-gradient(circle at 12% 0%, rgba(46, 204, 113, 0.12), transparent 30%);
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.24);
            backdrop-filter: blur(12px);
        }

        .workflow-card::after {
            content: "";
            position: absolute;
            inset: auto -25% -45% 35%;
            height: 90px;
            background: radial-gradient(circle, rgba(46, 204, 113, 0.16), transparent 62%);
            pointer-events: none;
        }

        .workflow-index {
            width: 2rem;
            height: 2rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            background: rgba(46, 204, 113, 0.1);
            border: 1px solid rgba(46, 204, 113, 0.28);
            color: #BDF7D4;
            font-weight: 800;
            margin-bottom: 0.7rem;
        }

        .workflow-card h4 {
            margin: 0 0 0.35rem;
            color: #F8FAFC;
            font-size: 0.96rem;
        }

        .workflow-card p {
            margin: 0;
            color: #AEB7C4;
            font-size: 0.84rem;
            line-height: 1.45;
        }

        .source-shell {
            display: grid;
            grid-template-columns: 1.35fr 0.9fr;
            gap: 1rem;
            align-items: start;
            margin-top: 1rem;
        }

        .readiness-panel {
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 1rem;
            background: rgba(15, 23, 42, 0.35);
            box-shadow: 0 12px 38px rgba(0, 0, 0, 0.2);
        }

        .readiness-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.9rem;
            padding: 0.72rem 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.07);
        }

        .readiness-row:last-child {
            border-bottom: 0;
        }

        .readiness-label {
            color: #D8DEE9;
            font-size: 0.88rem;
            font-weight: 700;
        }

        .readiness-value {
            color: #BDF7D4;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }

        .agent-rail {
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 1rem;
            margin: 1rem 0;
            background: linear-gradient(135deg, rgba(22, 27, 34, 0.64), rgba(11, 13, 16, 0.78));
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
        }

        .agent-rail-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.85rem;
        }

        .agent-rail h3 {
            margin: 0;
            font-size: 1.05rem;
        }

        .agent-subtitle {
            color: #AEB7C4;
            font-size: 0.78rem;
            margin-top: 0.16rem;
        }

        .agent-progress-label {
            color: #BDF7D4;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            white-space: nowrap;
        }

        .agent-progress-track {
            height: 0.42rem;
            width: 100%;
            overflow: hidden;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.06);
            margin-bottom: 0.4rem;
        }

        .agent-progress-bar {
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, rgba(46, 204, 113, 0.72), rgba(189, 247, 212, 0.96));
            box-shadow: 0 0 18px rgba(46, 204, 113, 0.32);
            transition: width 260ms ease;
        }

        .agent-step {
            display: grid;
            grid-template-columns: 2rem 1fr auto;
            gap: 0.75rem;
            align-items: center;
            padding: 0.78rem;
            border-top: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 14px;
            transition: background 180ms ease, border-color 180ms ease, opacity 180ms ease;
        }

        .agent-step.pending {
            opacity: 0.72;
        }

        .agent-step.active {
            background: rgba(46, 204, 113, 0.06);
            border-top-color: rgba(46, 204, 113, 0.18);
        }

        .agent-dot {
            width: 1.85rem;
            height: 1.85rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            border: 1px solid rgba(148, 163, 184, 0.24);
            color: #94A3B8;
            background: rgba(15, 23, 42, 0.5);
            font-size: 0.78rem;
            font-weight: 800;
        }

        .agent-step.active .agent-dot {
            color: #0B0D10;
            border-color: rgba(46, 204, 113, 0.9);
            background: #2ECC71;
            box-shadow: 0 0 18px rgba(46, 204, 113, 0.38);
            animation: agentPulse 1.15s ease-in-out infinite;
        }

        .agent-step.done .agent-dot {
            color: #BDF7D4;
            border-color: rgba(46, 204, 113, 0.46);
            background: rgba(46, 204, 113, 0.12);
        }

        .agent-name {
            color: #F8FAFC;
            font-weight: 800;
            font-size: 0.92rem;
        }

        .agent-desc {
            color: #AEB7C4;
            font-size: 0.8rem;
            margin-top: 0.12rem;
        }

        .agent-state {
            color: #94A3B8;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .agent-phase {
            color: #BDF7D4;
            font-size: 0.66rem;
            font-weight: 800;
            letter-spacing: 0.11em;
            text-transform: uppercase;
            margin-bottom: 0.1rem;
        }

        .agent-step.active .agent-state,
        .agent-step.done .agent-state {
            color: #BDF7D4;
        }

        .upload-confirm {
            margin-top: 0.75rem;
            padding: 0.72rem 0.82rem;
            border-radius: 13px;
            color: #BDF7D4;
            background: rgba(46, 204, 113, 0.08);
            border: 1px solid rgba(46, 204, 113, 0.22);
            font-size: 0.8rem;
            font-weight: 700;
        }

        @keyframes agentPulse {
            0%, 100% {
                box-shadow: 0 0 10px rgba(46, 204, 113, 0.28);
                transform: scale(1);
            }
            50% {
                box-shadow: 0 0 24px rgba(46, 204, 113, 0.58);
                transform: scale(1.04);
            }
        }

        @media (max-width: 900px) {
            .workflow-grid,
            .source-shell {
                grid-template-columns: 1fr;
            }
        }

        hr {
            border-color: rgba(255, 255, 255, 0.08);
            margin-top: 2rem;
            margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def load_protocol(name: str) -> str:
    try:
        return AGENT_FILES[name].read_text(encoding="utf-8")
    except OSError as exc:
        LOGGER.exception("Protocol load failed | name=%s", name)
        raise PipelineFailure(PipelinePhase.STRUCTURAL_EXTRACTION, f"Missing protocol file: {name}", exc) from exc


def load_template(name: str) -> str:
    try:
        return TEMPLATE_FILES[name].read_text(encoding="utf-8")
    except OSError as exc:
        LOGGER.exception("Template load failed | name=%s", name)
        raise PipelineFailure(PipelinePhase.DOCUMENT_COMPILATION, f"Missing output template: {name}", exc) from exc


def parse_upload(uploaded_file: Any | None) -> str:
    if uploaded_file is None:
        return ""

    name = uploaded_file.name.lower()
    raw = uploaded_file.getvalue()
    if name.endswith((".txt", ".md", ".markdown")):
        LOGGER.info("Uploaded text file parsed | filename=%s | bytes=%s", uploaded_file.name, len(raw))
        return raw.decode("utf-8", errors="replace")

    raise ValueError("Only TXT and Markdown uploads are enabled in this release.")


def parse_uploads(uploaded_files: list[Any] | None) -> str:
    if not uploaded_files:
        return ""

    text_segments: list[str] = []
    for uploaded_file in uploaded_files[:MAX_UPLOAD_FILES]:
        text_segments.append(parse_upload(uploaded_file))
    return "\n\n".join(segment.strip() for segment in text_segments if segment.strip())


def upload_signature(uploaded_files: list[Any] | None) -> tuple[tuple[str, int], ...]:
    if not uploaded_files:
        return ()
    return tuple((uploaded_file.name, len(uploaded_file.getvalue())) for uploaded_file in uploaded_files[:MAX_UPLOAD_FILES])


def merge_inputs(pasted_text: str, uploaded_text: str) -> str:
    segments = [part.strip() for part in (uploaded_text, pasted_text) if part and part.strip()]
    return "\n\n".join(segments)


def calculate_document_stats(text: str) -> DocumentStats:
    words = len(re.findall(r"\b[\w'-]+\b", text or ""))
    estimated_tokens = max(0, round(words * 1.33))
    completeness_score = estimate_completeness(text or "", words)
    return DocumentStats(words=words, estimated_tokens=estimated_tokens, completeness_score=completeness_score)


def estimate_completeness(text: str, words: int) -> int:
    if not text.strip():
        return 0

    signals = {
        "scope": ("scope", "objective", "deliverable", "requirement", "sow", "rfp"),
        "timeline": ("timeline", "deadline", "milestone", "phase", "week", "month"),
        "risk": ("risk", "dependency", "constraint", "assumption", "compliance"),
        "technical": ("api", "data", "cloud", "security", "integration", "architecture"),
        "qa": ("test", "qa", "acceptance", "validation", "regression", "uat"),
    }
    lower_text = text.lower()
    matched_groups = sum(any(term in lower_text for term in terms) for terms in signals.values())
    length_score = min(45, int(words / 18))
    signal_score = matched_groups * 10
    structure_score = min(10, text.count("\n") // 3)
    return max(8, min(100, length_score + signal_score + structure_score))


def validate_ingestion(document_text: str, stats: DocumentStats) -> None:
    if not document_text.strip():
        raise PipelineFailure(PipelinePhase.INGESTION, "No document text was supplied.")
    if stats.words < 25:
        raise PipelineFailure(
            PipelinePhase.INGESTION,
            "The document is too short for reliable presales extraction. Add at least 25 words of source material.",
        )


def split_source_sentences(document_text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", document_text.strip())
    candidates = re.split(r"(?<=[.!?])\s+|(?:\n|•|- )+", normalized)
    cleaned = [candidate.strip(" -•\t") for candidate in candidates if len(candidate.strip()) >= 18]
    if cleaned:
        return cleaned[:18]
    words = normalized.split()
    return [" ".join(words[index : index + 22]) for index in range(0, min(len(words), 88), 22) if words[index : index + 22]]


def select_relevant_items(sentences: list[str], keywords: tuple[str, ...], fallback: list[str], limit: int = 4) -> list[str]:
    matches: list[str] = []
    for sentence in sentences:
        lower_sentence = sentence.lower()
        if any(keyword in lower_sentence for keyword in keywords):
            matches.append(sentence.rstrip(".") + ".")
        if len(matches) >= limit:
            break
    return matches or fallback[:limit]


def local_rfp_agent(document_text: str) -> ScopeRequirements:
    sentences = split_source_sentences(document_text)
    stats = calculate_document_stats(document_text)
    summary_subject = sentences[0].rstrip(".") if sentences else "The submitted source package"

    objectives = select_relevant_items(
        sentences,
        ("objective", "goal", "scope", "requirement", "implement", "deliver", "migrate", "build"),
        [
            "Clarify business objectives, delivery scope, and measurable implementation outcomes.",
            "Convert source requirements into a practical delivery plan with accountable workstreams.",
            "Define acceptance checkpoints so stakeholders can validate readiness before rollout.",
        ],
    )
    deliverables = select_relevant_items(
        sentences,
        ("deliverable", "report", "dashboard", "integration", "migration", "workflow", "portal", "document"),
        [
            "Executive scope brief with prioritized delivery outcomes.",
            "Implementation backlog with milestones, constraints, and acceptance checkpoints.",
            "Operational readiness package for rollout, support, and stakeholder handoff.",
        ],
    )
    constraints = select_relevant_items(
        sentences,
        ("constraint", "compliance", "security", "deadline", "timeline", "dependency", "budget", "risk", "legacy"),
        [
            "Final scope must account for timeline, dependency, security, compliance, and operational readiness constraints.",
            "Delivery plan should preserve business continuity while source requirements are clarified.",
            "Outstanding assumptions should be reviewed with stakeholders before production commitment.",
        ],
    )

    deadline_matches = [
        sentence.rstrip(".") + "."
        for sentence in sentences
        if re.search(r"\b(week|month|phase|milestone|deadline|q[1-4]|day|date|launch|rollout)\b", sentence, re.I)
    ][:3]
    deadline_source = deadline_matches or [
        "Discovery and source confirmation.",
        "Delivery planning and risk review.",
        "Implementation readiness and executive handoff.",
    ]
    deadlines = [
        Deadline(
            milestone=item,
            timeframe=f"Phase {index + 1}",
            business_value="Creates a clear decision checkpoint for scope, delivery confidence, and stakeholder alignment.",
        )
        for index, item in enumerate(deadline_source)
    ]

    checklist = [
        "Confirm business owner, decision maker, and acceptance criteria.",
        "Validate scope boundaries, dependencies, and operational constraints.",
        "Map functional requirements into prioritized delivery workstreams.",
        "Review risk posture, mitigation ownership, and rollout readiness.",
        "Prepare executive briefing and delivery handoff artifacts.",
    ]

    return ScopeRequirements(
        executive_summary=(
            f"{summary_subject}. The local analysis engine reviewed {stats.words:,} words of source material and "
            "structured it into delivery scope, key requirements, constraints, milestones, and acceptance checkpoints."
        ),
        objectives=objectives,
        deliverables=deliverables,
        core_constraints=constraints,
        chronological_deadlines=deadlines,
        functional_checklist=checklist,
    )


def local_raid_agent(scope: ScopeRequirements, document_text: str) -> RiskRegister:
    lower_text = document_text.lower()
    risks: list[RiskItem] = []

    risk_rules = [
        (
            ("integration", "api", "dependency", "system", "legacy"),
            "Integration dependencies may be under-specified across source systems or stakeholder teams.",
            "Dependency",
            "High",
            "Run a dependency review, confirm interface ownership, and sequence delivery around validated integration checkpoints.",
        ),
        (
            ("security", "compliance", "privacy", "audit", "data"),
            "Security, compliance, or data handling requirements may require additional governance before rollout.",
            "Compliance",
            "High",
            "Confirm regulatory scope, evidence requirements, data controls, and approval owners before implementation begins.",
        ),
        (
            ("deadline", "timeline", "week", "month", "launch", "rollout"),
            "Timeline commitments may be at risk if discovery, approvals, or dependencies are not resolved early.",
            "Schedule",
            "Medium",
            "Create milestone gates with decision owners, escalation paths, and contingency planning for delayed inputs.",
        ),
        (
            ("budget", "cost", "staff", "resource", "team"),
            "Delivery capacity or budget assumptions may not match the required implementation workload.",
            "Resourcing",
            "Medium",
            "Validate staffing model, decision cadence, and delivery budget against the prioritized scope.",
        ),
    ]

    for keywords, factor, category, severity, mitigation in risk_rules:
        if any(keyword in lower_text for keyword in keywords):
            risks.append(
                RiskItem(
                    **{
                        "Risk Factor": factor,
                        "Category": category,
                        "Impact Severity": severity,
                        "Proactive Mitigation Strategy": mitigation,
                    }
                )
            )

    if not risks:
        risks.append(
            RiskItem(
                **{
                    "Risk Factor": "Source requirements may require stakeholder confirmation before delivery commitments are finalized.",
                    "Category": "Scope",
                    "Impact Severity": "Medium",
                    "Proactive Mitigation Strategy": "Run a structured scope review and document open questions before executive sign-off.",
                }
            )
        )

    risks.append(
        RiskItem(
            **{
                "Risk Factor": "Acceptance criteria may be interpreted differently across business, delivery, and QA stakeholders.",
                "Category": "Governance",
                "Impact Severity": "Medium",
                "Proactive Mitigation Strategy": "Create shared acceptance checkpoints and require sign-off before each delivery phase closes.",
            }
        )
    )
    return RiskRegister(raid_risk_matrix=risks[:5])


def local_qa_agent(scope: ScopeRequirements, risk_register: RiskRegister) -> QAIntelligence:
    high_risks = sum(risk.impact_severity == ImpactSeverity.HIGH for risk in risk_register.raid_risk_matrix)
    total_risks = len(risk_register.raid_risk_matrix)
    staffing_index = round(2.0 + (high_risks * 0.75) + (total_risks * 0.25), 1)

    return QAIntelligence(
        recommended_testing_stack="Business workflow validation + API checks + data reconciliation + release readiness review",
        testing_strategy=[
            "Validate core business workflows against agreed acceptance criteria.",
            "Confirm critical integrations and data exchanges before rollout decisions.",
            "Run regression checks for high-priority requirements and stakeholder-facing workflows.",
            "Review operational readiness, support handoff, and release evidence before launch.",
        ],
        tooling_frameworks=[
            "Business workflow test pack",
            "API and integration validation checklist",
            "Data reconciliation workbook",
            "Release readiness scorecard",
            "Stakeholder acceptance tracker",
        ],
        staffing_matrix=[
            StaffingItem(
                role="QA Lead",
                allocation="1 FTE",
                responsibility="Owns test strategy, acceptance checkpoints, and executive readiness reporting.",
            ),
            StaffingItem(
                role="Functional Test Analyst",
                allocation="1-2 FTE",
                responsibility="Validates business workflows, requirements coverage, and stakeholder acceptance evidence.",
            ),
            StaffingItem(
                role="Integration Validation Specialist",
                allocation="0.5 FTE",
                responsibility="Reviews data exchange, interface readiness, and cross-system delivery risks.",
            ),
            StaffingItem(
                role="Delivery Coordinator",
                allocation="0.5 FTE",
                responsibility="Tracks open decisions, release evidence, and sign-off readiness across stakeholders.",
            ),
        ],
        staffing_allocation_index=min(20, max(0.1, staffing_index)),
    )


def run_local_codex_backend(document_text: str) -> PresalesAnalysis:
    scope = local_rfp_agent(document_text)
    risk_register = local_raid_agent(scope, document_text)
    qa = local_qa_agent(scope, risk_register)
    return PresalesAnalysis(
        scope_requirements=scope,
        raid_risk_matrix=risk_register.raid_risk_matrix,
        qa_intelligence=qa,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        source_mode="local",
        validation_trace=[
            "Ingestion validated",
            "RFP Agent complete",
            "RAID Agent complete",
            "QA Agent complete",
        ],
    )


def get_mock_analysis(document_text: str, reason: str = "Demo fallback") -> PresalesAnalysis:
    analysis = MOCK_ANALYSIS.model_copy(deep=True)
    words = calculate_document_stats(document_text).words
    if words > 0:
        analysis.scope_requirements.executive_summary = (
            f"Prepared an executive briefing using the supplied {words:,}-word source package and a representative "
            "enterprise delivery scenario. Add richer source detail to make future analysis more specific."
        )
    analysis.generated_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    analysis.source_mode = "mock"
    return analysis


AGENT_STEPS = [
    ("Ingestion", "Source Validation", "Validate source material and calculate readiness signals."),
    ("Agent RFP", "Structural Extraction", "Extract scope, objectives, constraints, deliverables, and milestones."),
    ("Agent RAID", "Risk Mapping", "Map project risks, dependencies, severity, and mitigations."),
    ("Agent QA", "Briefing Assembly", "Build validation strategy, execution controls, and staffing estimates."),
]


def render_agent_progress(active_index: int = 0, completed_count: int = 0) -> None:
    rows = []
    for index, (name, phase, description) in enumerate(AGENT_STEPS):
        state_class = "done" if index < completed_count else "active" if index == active_index else "pending"
        state_label = "Complete" if index < completed_count else "Running" if index == active_index else "Queued"
        rows.append(
            f"""
            <div class="agent-step {state_class}">
                <div class="agent-dot">{index + 1}</div>
                <div>
                    <div class="agent-phase">{html.escape(phase)}</div>
                    <div class="agent-name">{html.escape(name)}</div>
                    <div class="agent-desc">{html.escape(description)}</div>
                </div>
                <div class="agent-state">{state_label}</div>
            </div>
            """
        )

    progress_percent = min(100, round((completed_count / len(AGENT_STEPS)) * 100))
    st.markdown(
        f"""
        <div class="agent-rail">
            <div class="agent-rail-header">
                <div>
                    <h3>Agent Orchestration</h3>
                    <div class="agent-subtitle">Sequential validation gates from intake to executive briefing.</div>
                </div>
                <div class="agent-progress-label">{progress_percent}% Complete</div>
            </div>
            <div class="agent-progress-track">
                <div class="agent-progress-bar" style="width: {progress_percent}%"></div>
            </div>
            {''.join(rows)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def execute_pipeline(document_text: str) -> PresalesAnalysis:
    stats = calculate_document_stats(document_text)
    progress_slot = st.empty()

    with st.spinner("Orchestrating AI Presales Agents..."):
        try:
            with progress_slot.container():
                render_agent_progress(active_index=0, completed_count=0)
            LOGGER.info("Pipeline phase started | phase=%s | words=%s", PipelinePhase.INGESTION.value, stats.words)
            validate_ingestion(document_text, stats)
            time.sleep(0.25)
            with progress_slot.container():
                render_agent_progress(active_index=1, completed_count=1)
            scope = local_rfp_agent(document_text)
            time.sleep(0.2)
            with progress_slot.container():
                render_agent_progress(active_index=2, completed_count=2)
            risk_register = local_raid_agent(scope, document_text)
            time.sleep(0.2)
            with progress_slot.container():
                render_agent_progress(active_index=3, completed_count=3)
            qa = local_qa_agent(scope, risk_register)
            analysis = PresalesAnalysis(
                scope_requirements=scope,
                raid_risk_matrix=risk_register.raid_risk_matrix,
                qa_intelligence=qa,
                generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                source_mode="local",
                validation_trace=[
                    "Ingestion validated",
                    "Agent RFP complete",
                    "Agent RAID complete",
                    "Agent QA complete",
                ],
            )
            with progress_slot.container():
                render_agent_progress(active_index=3, completed_count=4)
            LOGGER.info("Pipeline complete | mode=local | risks=%s", len(analysis.raid_risk_matrix))
            return analysis
        except (PipelineFailure, ValueError) as exc:
            LOGGER.exception("Pipeline fallback | error_type=%s | message=%s", type(exc).__name__, exc)
            st.error("We need more source detail before generating a complete briefing.")
            return get_mock_analysis(document_text, "Sample analysis")


def render_header() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="status-pill">● Executive Presales Workspace</div>
            <h1 class="hero-title">AI Delivery & Presales Assistant</h1>
            <p class="hero-subtitle">
                Transform RFP and SOW source material into a polished executive scope, risk view,
                QA plan, staffing estimate, and client-ready briefing exports.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    st.sidebar.markdown("## Workspace")
    st.sidebar.markdown("### Navigation")
    st.sidebar.markdown("- Intake")
    if st.session_state.get("analysis_ready"):
        st.sidebar.markdown("- Executive Outputs")
        st.sidebar.markdown("- Export Center")
    else:
        st.sidebar.markdown("- Outputs unlock after processing")

    st.sidebar.divider()
    st.sidebar.markdown("### Project State")
    if st.session_state.get("analysis_ready"):
        st.sidebar.success("Briefing ready")
        st.sidebar.caption(f"Last run: {st.session_state.get('last_run_at', 'Current session')}")
    else:
        st.sidebar.info("Awaiting source material")

    st.sidebar.divider()
    st.sidebar.markdown("### Engine")
    st.sidebar.success("Analysis engine ready")


def render_intake_overview() -> None:
    st.markdown('<div class="ux-section-kicker">Workflow</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="workflow-grid">
            <div class="workflow-card">
                <div class="workflow-index">1</div>
                <h4>Load Source</h4>
                <p>Paste discovery notes or upload up to five TXT/Markdown source files.</p>
            </div>
            <div class="workflow-card">
                <div class="workflow-index">2</div>
                <h4>Check Readiness</h4>
                <p>Review word count and completeness before running the analysis.</p>
            </div>
            <div class="workflow-card">
                <div class="workflow-index">3</div>
                <h4>Run Agents</h4>
                <p>RFP, RAID, and QA agents execute sequentially with validation gates.</p>
            </div>
            <div class="workflow-card">
                <div class="workflow-index">4</div>
                <h4>Export Briefing</h4>
                <p>Open executive tabs, then download Word and PowerPoint outputs.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_readiness_panel(stats: DocumentStats, uploaded_count: int) -> None:
    if stats.words >= 250 and stats.completeness_score >= 70:
        posture = "Strong"
    elif stats.words >= 25:
        posture = "Usable"
    else:
        posture = "Needs Source"

    st.markdown(
        f"""
        <div class="readiness-panel">
            <div class="readiness-row">
                <span class="readiness-label">Source posture</span>
                <span class="readiness-value">{posture}</span>
            </div>
            <div class="readiness-row">
                <span class="readiness-label">Files attached</span>
                <span class="readiness-value">{uploaded_count}/{MAX_UPLOAD_FILES}</span>
            </div>
            <div class="readiness-row">
                <span class="readiness-label">Current path</span>
                <span class="readiness-value">Intake → Agents → Briefing</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_ingestion() -> tuple[str, DocumentStats]:
    left, right = st.columns([1.18, 0.82], gap="large")
    uploaded_files = None
    uploaded_text = ""
    uploaded_count = 0

    with right:
        with st.container(border=True):
            st.markdown('<span class="ux-upload-card"></span>', unsafe_allow_html=True)
            st.markdown("### Document Upload")
            st.caption(
                f"Upload up to {MAX_UPLOAD_FILES} TXT or Markdown files. File content is combined with pasted notes for analysis."
            )
            uploaded_files = st.file_uploader(
                "Upload source files",
                type=["txt", "md", "markdown"],
                accept_multiple_files=True,
            )
            if uploaded_files:
                try:
                    selected_files = uploaded_files[:MAX_UPLOAD_FILES]
                    uploaded_count = len(selected_files)
                    uploaded_text = parse_uploads(selected_files)
                    signature = upload_signature(selected_files)
                    if signature and signature != st.session_state.get("uploaded_source_signature"):
                        st.session_state.uploaded_source_signature = signature
                        st.session_state.source_text = uploaded_text
                        st.session_state.pending_upload_analysis = True
                        st.session_state.analysis_ready = False
                    st.markdown(
                        f"""
                        <div class="upload-confirm">
                            {len(selected_files)} source file{'s' if len(selected_files) != 1 else ''} staged.
                            The text box has been populated and the agent workflow will begin automatically.
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if len(uploaded_files) > MAX_UPLOAD_FILES:
                        st.info(f"Using the first {MAX_UPLOAD_FILES} files for this analysis.")
                except ValueError as exc:
                    LOGGER.exception("Upload parsing failed | message=%s", exc)
                    st.error("We could not read that file. Please upload a TXT or Markdown document.")

    with left:
        with st.container(border=True):
            st.markdown('<span class="ux-intake-card"></span>', unsafe_allow_html=True)
            st.markdown("### Input Ingestion Hub")
            st.caption(
                "Paste RFP, SOW, discovery notes, constraints, compliance language, milestones, and acceptance criteria. "
                "Uploaded Markdown/TXT content appears here before the agents begin."
            )
            pasted_text = st.text_area(
                "Raw enterprise document text",
                height=305,
                key="source_text",
                label_visibility="collapsed",
                placeholder=(
                    "Paste technical requirements, implementation scope, milestones, risks, assumptions, "
                    "and QA expectations..."
                ),
            )

    document_text = pasted_text
    stats = calculate_document_stats(document_text)
    metric_cols = st.columns(2)
    metric_cols[0].metric("Total Words", f"{stats.words:,}")
    metric_cols[1].metric("Completeness Score", f"{stats.completeness_score}/100")
    render_readiness_panel(stats, uploaded_count)
    return document_text, stats


def render_scope_tab(scope: ScopeRequirements) -> None:
    with st.container(border=True):
        st.subheader("Scope & Functional Requirements")
        st.markdown("### Executive Objective")
        st.write(scope.executive_summary)

        card_cols = st.columns(3)
        card_data = [
            ("Objectives", scope.objectives),
            ("Deliverables", scope.deliverables),
            ("Core Constraints", scope.core_constraints),
        ]
        for col, (title, items) in zip(card_cols, card_data, strict=False):
            with col:
                st.markdown(
                    f"""
                    <div class="mini-card">
                        <h4>{html.escape(title)}</h4>
                        <p>{len(items)} validated signals</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(format_bullets(items))

        st.markdown("### Chronological Deadlines")
        st.dataframe(
            pd.DataFrame([deadline.model_dump() for deadline in scope.chronological_deadlines]),
            width="stretch",
            hide_index=True,
            height=245,
        )

        st.markdown("### Functional Checklist")
        st.markdown(format_checklist(scope.functional_checklist))


def render_risk_tab(risks: list[RiskItem]) -> None:
    with st.container(border=True):
        st.subheader("RAID & Risk Matrix")
        risk_frame = pd.DataFrame([risk.model_dump(by_alias=True) for risk in risks])
        expected_columns = ["Risk Factor", "Category", "Impact Severity", "Proactive Mitigation Strategy"]
        st.data_editor(
            risk_frame[expected_columns],
            width="stretch",
            hide_index=True,
            disabled=True,
            height=520,
            column_config={
                "Risk Factor": st.column_config.TextColumn("Risk Factor", width="large"),
                "Category": st.column_config.TextColumn("Category", width="medium"),
                "Impact Severity": st.column_config.SelectboxColumn(
                    "Impact Severity",
                    options=["High", "Medium", "Low"],
                    width="small",
                ),
                "Proactive Mitigation Strategy": st.column_config.TextColumn(
                    "Proactive Mitigation Strategy",
                    width="large",
                ),
            },
        )

        cols = st.columns(3)
        cols[0].metric("High Impact", sum(risk.impact_severity == ImpactSeverity.HIGH for risk in risks))
        cols[1].metric("Medium Impact", sum(risk.impact_severity == ImpactSeverity.MEDIUM for risk in risks))
        cols[2].metric("Low Impact", sum(risk.impact_severity == ImpactSeverity.LOW for risk in risks))


def render_qa_tab(qa: QAIntelligence) -> None:
    with st.container(border=True):
        st.subheader("QA Intelligence & Staffing")
        stack_col, strategy_col = st.columns([0.82, 1.18], gap="large")
        with stack_col:
            st.metric("Recommended Validation Approach", qa.recommended_testing_stack)
            st.metric("Staffing Allocation Index", f"{qa.staffing_allocation_index:.1f} FTE")
            st.markdown("### Execution Controls")
            st.markdown(format_bullets(qa.tooling_frameworks))
        with strategy_col:
            st.markdown("### Automated Regression Strategy")
            st.markdown(format_checklist(qa.testing_strategy))

        st.markdown("### Estimated Resource Allocations")
        st.dataframe(
            pd.DataFrame([person.model_dump() for person in qa.staffing_matrix]),
            width="stretch",
            hide_index=True,
            height=260,
        )


def format_bullets(items: list[str]) -> str:
    if not items:
        return "_No extracted items._"
    return "\n".join(f"- **{item.strip()}**" for item in items)


def format_checklist(items: list[str]) -> str:
    if not items:
        return "_No checklist items available._"
    return "\n".join(f"- [ ] {item.strip()}" for item in items)


def render_output_interface(analysis: PresalesAnalysis) -> None:
    st.success("Executive briefing ready.")
    scope_tab, risk_tab, qa_tab = st.tabs(
        ["📋 Scope & Requirements", "⚠️ RAID & Risk Matrix", "🔧 QA Intelligence & Staffing"]
    )
    with scope_tab:
        render_scope_tab(analysis.scope_requirements)
    with risk_tab:
        render_risk_tab(analysis.raid_risk_matrix)
    with qa_tab:
        render_qa_tab(analysis.qa_intelligence)


def render_export_center(analysis: PresalesAnalysis) -> None:
    st.markdown("---")
    st.subheader("Export Center")
    col_word, col_ppt = st.columns(2, gap="large")
    data = analysis.model_dump(mode="json", by_alias=True)
    with col_word:
        try:
            word_bytes = generate_word_document(data)
            st.download_button(
                "📥 Export Word Briefing",
                data=word_bytes,
                file_name="presales_executive_briefing.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
            )
        except Exception as exc:
            LOGGER.exception("Word export failed | message=%s", exc)
            st.error("Word export is temporarily unavailable.")
    with col_ppt:
        try:
            ppt_bytes = generate_presentation_slides(data)
            st.download_button(
                "📊 Download Pitch Deck (.pptx)",
                data=ppt_bytes,
                file_name="presales_pitch_deck.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                width="stretch",
            )
        except Exception as exc:
            LOGGER.exception("Presentation export failed | message=%s", exc)
            st.error("Pitch deck export is temporarily unavailable.")


def coerce_session_analysis(value: Any, document_text: str) -> PresalesAnalysis:
    if isinstance(value, PresalesAnalysis):
        return value

    LOGGER.warning("Session analysis migration fallback | previous_type=%s", type(value).__name__)
    return get_mock_analysis(document_text, "Session migration fallback")


def main() -> None:
    LOGGER.info("App render started")
    configure_page()
    render_sidebar()
    render_header()
    render_intake_overview()

    document_text, stats = render_ingestion()

    run_clicked = st.button("Run Presales Intelligence Engine", type="primary", width="stretch")
    pending_upload_analysis = bool(st.session_state.get("pending_upload_analysis"))
    if run_clicked or pending_upload_analysis:
        st.session_state.pending_upload_analysis = False
        if pending_upload_analysis:
            st.toast("Source loaded. Starting agent orchestration.", icon=":material/automation:")
        st.session_state.analysis = execute_pipeline(document_text)
        st.session_state.active_stats = stats.model_dump()
        st.session_state.analysis_ready = True
        st.session_state.last_run_at = datetime.now(UTC).strftime("%b %d, %Y %I:%M %p UTC")
    elif "analysis" in st.session_state:
        st.session_state.analysis = coerce_session_analysis(st.session_state.analysis, document_text)

    if st.session_state.get("analysis_ready") and "analysis" in st.session_state:
        analysis: PresalesAnalysis = st.session_state.analysis
        render_output_interface(analysis)
        render_export_center(analysis)


if __name__ == "__main__":
    main()

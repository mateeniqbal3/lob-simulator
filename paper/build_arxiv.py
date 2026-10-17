"""Build an arXiv-ready LaTeX source bundle from paper/writeup.md.

arXiv compiles submissions with pdfLaTeX, so this produces a single
self-contained main.tex (standard packages only, references inline, no
BibTeX step) plus the figures it uses:

    paper/arxiv/main.tex             LaTeX source (committed)
    paper/arxiv/arxiv_submission.zip main.tex + figures/, ready to upload

main.tex looks for figures in figures/ (inside the zip) and ../figures/
(inside the repository), so it compiles in both places.

Requirements: pandoc (3.x). pdflatex is needed only for the optional check.
Usage (from the repository root):
    python paper/build_arxiv.py            # write main.tex and the zip
    python paper/build_arxiv.py --check    # also compile the zip with pdflatex
"""

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# Width of each figure as a fraction of the text width (default 0.72).
FIG_WIDTH: dict[str, float] = {"fig1_event_study.png": 0.78, "fig2_effective_spread.png": 0.62}
DEFAULT_WIDTH = 0.75

PAPER = Path(__file__).resolve().parent
SRC = PAPER / "writeup.md"
OUT_DIR = PAPER / "arxiv"
FIG_DIR = PAPER / "figures"


def to_latex(md: str) -> str:
    """Convert a Markdown fragment to a LaTeX fragment with pandoc."""
    result = subprocess.run(
        [
            "pandoc",
            "--from",
            "markdown+tex_math_dollars+pipe_tables+raw_attribute",
            "--to",
            "latex",
            "--wrap=preserve",
        ],
        input=md,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


text = SRC.read_text(encoding="utf-8")

# Title block: everything before the first horizontal rule.
head, body = text.split("\n---\n", 1)
title = re.search(r"^# (.+)$", head, re.MULTILINE).group(1).strip()
head_lines = [ln.strip() for ln in head.splitlines() if ln.strip() and not ln.startswith("# ")]
author = head_lines[0].strip("*")
affiliation, email, version = head_lines[1:4]
repo_url = re.search(r"<(.+?)>", "\n".join(head_lines)).group(1)
date = version.split("—")[-1].strip() if "—" in version else version

# Abstract, keywords and JEL codes: up to the next horizontal rule.
abstract_block, body = body.split("\n---\n", 1)
paras = [p.strip() for p in abstract_block.replace("## Abstract", "").strip().split("\n\n")]
keywords = next(p for p in paras if p.startswith("**Keywords"))
jel = next((p for p in paras if p.startswith("**JEL")), None)
abstract = "\n\n".join(p for p in paras if p not in (keywords, jel))

# --- Body transformations (GitHub Markdown -> pandoc Markdown for LaTeX) ---

# Figures: use the italic caption under each image as the LaTeX caption,
# without the hand-written "Figure N." prefix (LaTeX numbers figures itself).
fig_re = re.compile(
    r"^!\[[^\]\n]*\]\((?:[^)\n]*/)?([^)/\n]+)\)\n\n\*Figure \d+\.\s*(.*?)\*\n",
    re.MULTILINE | re.DOTALL,
)


def figure(m: re.Match) -> str:
    name, caption = m.group(1), " ".join(m.group(2).split())
    width = FIG_WIDTH.get(name, DEFAULT_WIDTH)
    return f"![{caption}]({name}){{width={width * 100:.0f}%}}\n"


body = fig_re.sub(figure, body)
# Horizontal rules (before References and the appendices) are GitHub-only.
body = re.sub(r"^---\s*$", "", body, flags=re.MULTILINE)
# Pandoc needs a blank line before a list; GitHub does not.
body = re.sub(r"^(?![-\d\s|*]|\*\*Table)(.+)\n(?=- |\d+\. )", r"\1\n\n", body, flags=re.MULTILINE)
body = re.sub(r"^(\*\*[^\n]*)\n(?=- |\d+\. )", r"\1\n\n", body, flags=re.MULTILINE)
# Put each 64-character hash on its own line so it fits the text width.
body = re.sub(r": `([0-9a-f]{64})`", r":\\\n  `\1`", body)

# Headings: hand-numbered sections become LaTeX-numbered ones (same numbers),
# unnumbered ones stay unnumbered, and appendices get LaTeX appendix numbering.
appendix_started = False


def heading(m: re.Match) -> str:
    global appendix_started
    level, rest = m.group(1), m.group(2).strip()
    level = level[1:]  # "## " -> "# " (section), "### " -> "## " (subsection)
    numbered = re.match(r"^\d+(?:\.\d+)*\.?\s+(.*)$", rest)
    appendix = re.match(r"^Appendix [A-Z]\.\s*(.*)$", rest)
    if appendix:
        prefix = "" if appendix_started else "```{=latex}\n\\appendix\n```\n\n"
        appendix_started = True
        return f"{prefix}{level} {appendix.group(1)}"
    if numbered:
        return f"{level} {numbered.group(1)}"
    return f"{level} {rest} {{-}}"


# References: a list with hanging indents.
ref = re.search(r"^## References[^\n]*\n", body, flags=re.MULTILINE)
if ref:
    nxt = re.search(r"^## ", body[ref.end() :], flags=re.MULTILINE)
    end = ref.end() + nxt.start() if nxt else len(body)
    entries = [e.strip() for e in body[ref.end() : end].split("\n\n") if e.strip()]
    entries = [re.sub(r"^- ", "", e) for e in entries]
    items = "\n\n".join("`\\item`{=latex} " + e for e in entries)
    body = (
        body[: ref.end()] + "\n```{=latex}\n\\begin{list}{}{\\setlength{\\leftmargin}{1.5em}"
        "\\setlength{\\itemindent}{-1.5em}\\setlength{\\itemsep}{2pt}"
        "\\setlength{\\parsep}{0pt}}\n```\n\n"
        + items
        + "\n\n```{=latex}\n\\end{list}\n```\n\n"
        + body[end:]
    )

body = re.sub(r"^(#{2,3}) (.+)$", heading, body, flags=re.MULTILINE)

body_tex = to_latex(body)
# Keep short tables, and the bold "Table N." caption above them, on one page.
# Long tables (over 16 rows) still break across pages normally.
body_tex = re.sub(
    r"(\\textbf\{Table [^\n]*(?:\n[^\n]+)*\n\n)?(\\begin\{longtable\}.*?\\end\{longtable\})",
    lambda m: (
        ("\\needspace{18\\baselineskip}\n" if m.group(2).count("\\\\") <= 16 else "")
        + (m.group(1) or "")
        + m.group(2)
    ),
    body_tex,
    flags=re.DOTALL,
)
abstract_tex = to_latex(abstract)
keywords_tex = to_latex(keywords)
jel_tex = to_latex(jel) if jel else ""
title_tex = to_latex(title)
affiliation_tex = to_latex(affiliation)

# Short running title for the page header: the part of the title before a colon.
short_title = to_latex(title.split(":")[0] if ":" in title else title.split(",")[0])

PREAMBLE = r"""\pdfoutput=1
\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{textcomp}
\usepackage{mathpazo}
\usepackage{microtype}
\usepackage[margin=1in]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\graphicspath{{figures/}{../figures/}}
\setkeys{Gin}{keepaspectratio}
\usepackage{longtable,booktabs,array,calc}
\usepackage{float}
\floatplacement{figure}{H}
\usepackage{caption}
\captionsetup{font=small,labelfont=bf}
\usepackage{needspace}
\usepackage{setspace}
\setstretch{1.1}
\usepackage{fancyhdr}
\usepackage{etoolbox}
\usepackage{upquote}
\usepackage[hyphens]{xurl}
\usepackage[colorlinks=true,linkcolor=blue,urlcolor=blue,citecolor=blue]{hyperref}
\usepackage{bookmark}

% Characters pdfLaTeX does not define by default.
\DeclareUnicodeCharacter{2212}{\ensuremath{-}}
\DeclareUnicodeCharacter{0394}{\ensuremath{\Delta}}
\DeclareUnicodeCharacter{03B1}{\ensuremath{\alpha}}
\DeclareUnicodeCharacter{03B2}{\ensuremath{\beta}}
\DeclareUnicodeCharacter{03BB}{\ensuremath{\lambda}}
\DeclareUnicodeCharacter{03C3}{\ensuremath{\sigma}}
\DeclareUnicodeCharacter{2208}{\ensuremath{\in}}
\DeclareUnicodeCharacter{2248}{\ensuremath{\approx}}
\DeclareUnicodeCharacter{221D}{\ensuremath{\propto}}
\DeclareUnicodeCharacter{2264}{\ensuremath{\leq}}
\DeclareUnicodeCharacter{2265}{\ensuremath{\geq}}
\DeclareUnicodeCharacter{2192}{\ensuremath{\rightarrow}}

% Macros used by pandoc's LaTeX output.
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\makeatletter
\def\fps@figure{H}
\makeatother
\setlength{\emergencystretch}{3em}
\sloppy
\AtBeginEnvironment{longtable}{\footnotesize}
"""

pdf_title = re.sub(r"[{}\\]", "", title_tex)
jel_line = "\\noindent " + jel_tex if jel_tex else ""

doc = f"""{PREAMBLE}
\\hypersetup{{pdftitle={{{pdf_title}}}, pdfauthor={{{author}}}}}

\\pagestyle{{fancy}}
\\fancyhf{{}}
\\fancyhead[L]{{\\small {short_title}}}
\\fancyhead[R]{{\\small {author}}}
\\fancyfoot[C]{{\\thepage}}
\\renewcommand{{\\headrulewidth}}{{0.4pt}}

\\title{{{title_tex}}}
\\author{{{author}\\\\[2pt]
  {{\\normalsize {affiliation_tex}}}\\\\
  {{\\normalsize\\texttt{{{email}}}}}}}
\\date{{{date}\\\\[2pt] {{\\small Code and data: \\url{{{repo_url}}}}}}}

\\begin{{document}}
\\maketitle
\\thispagestyle{{empty}}

\\begin{{abstract}}
{abstract_tex}

\\medskip
\\noindent {keywords_tex}

{jel_line}
\\end{{abstract}}

{body_tex}

\\end{{document}}
"""

OUT_DIR.mkdir(exist_ok=True)
main_tex = OUT_DIR / "main.tex"
main_tex.write_text(doc, encoding="utf-8")

# Zip: main.tex plus only the figures it actually includes.
used = sorted(set(re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", doc)))
missing = [f for f in used if not (FIG_DIR / f).exists()]
if missing:
    sys.exit(f"Missing figures: {missing}")
zip_path = OUT_DIR / "arxiv_submission.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(main_tex, "main.tex")
    for f in used:
        z.write(FIG_DIR / f, f"figures/{f}")
print(f"Wrote {main_tex.relative_to(PAPER.parent)} and {zip_path.relative_to(PAPER.parent)}")
print(f"Figures: {', '.join(used)}")

if "--check" in sys.argv:
    # Compile the zip exactly as arXiv would receive it: pdflatex, twice.
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        for _ in range(2):
            run = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
            )
            if run.returncode != 0:
                sys.exit(run.stdout[-3000:])
        log = Path(tmp, "main.log").read_text(errors="replace")
        problems = [
            ln
            for ln in log.splitlines()
            if re.search(r"undefined|Missing character|Overfull \\hbox \((?:[2-9]\d|\d{3,})", ln)
        ]
        shutil.copy(Path(tmp, "main.pdf"), OUT_DIR / "main_check.pdf")
        pages = re.search(r"Output written on main.pdf \((\d+) page", log)
        print(f"pdflatex OK: {pages.group(1) if pages else '?'} pages")
        for ln in problems:
            print("  warning:", ln)

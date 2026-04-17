# convert.py / build_poster.py  (patched)
# -*- coding: utf-8 -*-
import json, re, pathlib, shutil, os, math

IMAGES_DIR_NAME = "<4o_4o>_images_and_tables"

def find_project_root(start: pathlib.Path) -> pathlib.Path:
    cur = start.resolve()
    for p in [cur] + list(cur.parents):
        if (p / "Paper2Poster").exists() or (p / IMAGES_DIR_NAME).exists() or (p / "test" / "cambridge_template.tex").exists():
            return p
    return cur

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT_DIR   = find_project_root(SCRIPT_DIR)
TEST_DIR   = ROOT_DIR / "test"

JSON_PATH        = TEST_DIR / "poster_content.json"
TEMPLATE_PATH    = TEST_DIR / "cambridge_template.tex"
ARRANGEMENT_PATH = TEST_DIR / "arrangement.json"
CAPTION_PATH     = TEST_DIR / "figure_caption.json"

OUTPUT_DIR       = TEST_DIR / "latex_proj"
OUTPUT_PATH      = OUTPUT_DIR / "poster_output_fix.tex"

IMAGES_PARENTS   = [ROOT_DIR / "Paper2Poster", ROOT_DIR]

# ---------- 版式与字号 ----------
BEAMER_SCALE_TARGET   = 1.15
TITLE_SIZE_SINGLE     = r"\Huge"
TITLE_SIZE_WRAP1      = r"\huge"
TITLE_SIZE_WRAP2PLUS  = r"\LARGE"
AUTHOR_SIZE_CMD       = r"\Large"
INSTITUTE_SIZE_CMD    = r"\large"
BLOCK_TITLE_SIZE_CMD  = r"\Large"
BLOCK_BODY_SIZE_CMD   = r"\large"
CAPTION_SIZE_CMD      = r"\normalsize"

BAPOSTER_FONTSCALE_TARGET = 0.31
TITLE_EM_HEIGHT = "6em"
RIGHT_LOGO_FILENAME = "logo.png"

FIG_ENLARGE_FACTOR    = 1.18
FIG_MIN_FRAC          = 0.60
FIG_MAX_FRAC          = 0.98
BASE_FIG_RATIO_LIMIT  = 0.58
TEXT_CHAR_PER_LINE    = 95
LINE_HEIGHT_WEIGHT    = 0.015

RIGHT_LOGO_INNERSEP_CM= 2.0
RIGHT_LOGO_XSHIFT_CM  = -2.0
RIGHT_LOGO_YSHIFT_CM  = 0.0
RIGHT_LOGO_HEIGHT_CM  = 6.0

# ### NEW: beamer 自适应列宽参数（不使用 span=2）
SEP_FRAC_DEFAULT      = 0.02   # 每个分隔列宽占 paperwidth 的比例
LONG_TITLE_THRESHOLD  = 38     # 标题长度阈值，触发加宽该列
W_HEAVY_BOOST         = 0.50   # 最重列的权重增量（默认三列基准权重=1）
COL_FRAC_MIN          = 0.26   # 单列最小占比（经验安全值）
COL_FRAC_MAX          = 0.42   # 单列最大占比（经验安全值）

def escape_text(s: str) -> str:
    if not s: return ""
    rep = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
           "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    for k, v in rep.items(): s = s.replace(k, v)
    return s

def soft_wrap_title_for_logo(title: str, first_limit=68, next_limit=72) -> str:
    if not title or len(title) <= first_limit: return title
    def break_at(s: str, limit: int):
        for sep in [": ", " - ", " — ", " – "]:
            idx = s.rfind(sep, 0, limit+1)
            if idx != -1: return s[:idx+len(sep)].rstrip(), s[idx+len(sep):].lstrip()
        idx = s.rfind(" ", 0, limit+1)
        if idx == -1: idx = limit
        return s[:idx].rstrip(), s[idx:].lstrip()
    head, rest = break_at(title, first_limit); parts = [head]
    if rest:
        if len(rest) > next_limit:
            mid, tail = break_at(rest, next_limit); parts.append(mid)
            if tail: parts.append(tail)
        else: parts.append(rest)
    return r" \\ ".join(parts)

def replace_command_balanced(tex: str, cmd: str, new_line: str) -> str:
    m = re.search(rf"\\{cmd}\b", tex)
    if not m: return tex
    i = m.end()
    if i < len(tex) and tex[i] == '[':
        depth = 1; i += 1
        while i < len(tex) and depth:
            if tex[i] == '[': depth += 1
            elif tex[i] == ']': depth -= 1
            i += 1
        while i < len(tex) and tex[i].isspace(): i += 1
    if i >= len(tex) or tex[i] != '{': return tex
    start = m.start(); j = i; depth = 0; end = None
    while j < len(tex):
        if tex[j] == '{': depth += 1
        elif tex[j] == '}':
            depth -= 1
            if depth == 0: end = j; break
        j += 1
    if end is None: return tex
    return tex[:start] + new_line + tex[end+1:]

def detect_template(tex: str) -> str:
    if re.search(r"\\documentclass[^}]*\{baposter\}", tex): return "baposter"
    return "beamer"

def norm_title(s: str) -> str:
    return " ".join((s or "").lower().replace("&", "and").split())

def slug_name(s: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "", norm_title(s))
    return base or "s"

CAP_PREFIX_RE = re.compile(
    r'^\s*(?:figure|fig\.?)\s*\d+(?:\s*[a-z]\)|\s*[a-z])?\s*[:：\.\-–—]\s*', re.IGNORECASE
)
def clean_caption_prefix(cap: str) -> str:
    if not cap: return ""
    return CAP_PREFIX_RE.sub("", cap).strip()

# ---------- beamer ----------
def choose_title_size_cmd(wrapped_title: str) -> str:
    br = wrapped_title.count("\\\\")
    return TITLE_SIZE_SINGLE if br==0 else (TITLE_SIZE_WRAP1 if br==1 else TITLE_SIZE_WRAP2PLUS)

def find_env_bounds(tex: str, env: str, start_pos: int):
    pat = re.compile(rf"\\(begin|end)\{{{re.escape(env)}\}}")
    depth = 0; begin_idx = None
    for m in pat.finditer(tex, start_pos):
        if m.group(1) == "begin":
            if depth == 0: begin_idx = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return begin_idx, m.end()
    return None, None

def extract_begin_token_with_options(region: str, env: str) -> str:
    m = re.match(rf"(\\begin\{{{re.escape(env)}\}}\s*(?:\[[^\]]*\])?)", region, re.S)
    return m.group(1) if m else f"\\begin{{{env}}}"

def split_even_continuous(items: list, n_cols: int) -> list[list]:
    n = len(items); base = n // n_cols; rem = n % n_cols
    out=[]; idx=0
    for i in range(n_cols):
        take = base + (1 if i < rem else 0)
        out.append(items[idx:idx+take]); idx += take
    return out

def bump_beamerposter_scale(tex: str, target: float) -> str:
    def repl(m):
        opts = m.group(1)
        opts2 = re.sub(r"scale\s*=\s*[\d.]+", "", opts)
        opts2 = re.sub(r",,", ",", opts2).strip().strip(",")
        opts2 = (opts2 + "," if opts2 else "") + f"scale={target}"
        return f"\\usepackage[{opts2}]{{beamerposter}}"
    return re.sub(r"\\usepackage\[(.*?)\]\{beamerposter\}", repl, tex, flags=re.S)

def inject_font_tweaks_beamer(tex: str, title_size_cmd: str) -> str:
    tweaks = (
        "\n% --- injected font tweaks (beamer) ---\n"
        f"\\setbeamerfont{{title}}{{size={title_size_cmd}}}\n"
        f"\\setbeamerfont{{author}}{{size={AUTHOR_SIZE_CMD}}}\n"
        f"\\setbeamerfont{{institute}}{{size={INSTITUTE_SIZE_CMD}}}\n"
        f"\\setbeamerfont{{block title}}{{size={BLOCK_TITLE_SIZE_CMD}}}\n"
        f"\\setbeamerfont{{block body}}{{size={BLOCK_BODY_SIZE_CMD}}}\n"
        f"\\setbeamerfont{{caption}}{{size={CAPTION_SIZE_CMD}}}\n"
        "\\setlength{\\abovecaptionskip}{4pt}\n"
        "\\setlength{\\belowcaptionskip}{3pt}\n"
    )
    pos = tex.find(r"\begin{document}")
    return tex[:pos] + tweaks + tex[pos:] if pos!=-1 else tex + tweaks

def inject_right_logo_beamer(tex: str) -> str:
    if "logo.png" in tex: return tex
    pos_head = tex.find(r"\addtobeamertemplate{headline}")
    node = (
        f"\n      \\node[anchor=north east, inner sep={RIGHT_LOGO_INNERSEP_CM}cm]"
        f" at ([xshift={RIGHT_LOGO_XSHIFT_CM}cm,yshift={RIGHT_LOGO_YSHIFT_CM}cm]current page.north east)\n"
        f"      {{\\includegraphics[height={RIGHT_LOGO_HEIGHT_CM}cm]{{logo.png}}}};\n"
    )
    if pos_head != -1:
        b,e = find_env_bounds(tex, "tikzpicture", tex.find(r"\begin{tikzpicture}", pos_head))
        if b is not None:
            return tex[:e-len(r"\end{tikzpicture}")] + node + tex[e:]
    add = (
        "\n% --- injected right-top logo (beamer) ---\n"
        "\\addtobeamertemplate{headline}{}\n"
        "{\n"
        "  \\begin{tikzpicture}[remember picture,overlay]\n"
        f"    \\node[anchor=north east, inner sep={RIGHT_LOGO_INNERSEP_CM}cm]"
        f" at ([xshift={RIGHT_LOGO_XSHIFT_CM}cm,yshift={RIGHT_LOGO_YSHIFT_CM}cm]current page.north east)\n"
        f"    {{\\includegraphics[height={RIGHT_LOGO_HEIGHT_CM}cm]{{logo.png}}}};\n"
        "  \\end{tikzpicture}\n"
        "}\n"
    )
    pos = tex.find(r"\begin{document}")
    return tex[:pos] + add + tex[pos:] if pos!=-1 else tex + add

# ### NEW: beamer 注入列宽宏（显式长度，避免偏左/右侧空白）
def inject_beamer_column_widths(tex: str, col_fracs, sep_frac: float) -> str:
    """
    col_fracs: [fA, fB, fC]，三列在 paperwidth 上的占比（不含 4 个分隔列）。
    sep_frac:  每个分隔列在 paperwidth 上的占比。
    """
    assert len(col_fracs) == 3
    # 这里直接设定长度为某个 \paperwidth 的比例，避免依赖模板里的 \colwidth / \separatorcolumn
    snippet = (
        "\n% --- injected beamer fixed column widths (auto) ---\n"
        "\\makeatletter\n"
        "\\newlength\\sepwidth\n"
        f"\\setlength\\sepwidth{{{sep_frac:.6f}\\paperwidth}}\n"
        "\\newlength\\colAwidth\\newlength\\colBwidth\\newlength\\colCwidth\n"
        f"\\setlength\\colAwidth{{{col_fracs[0]:.6f}\\paperwidth}}\n"
        f"\\setlength\\colBwidth{{{col_fracs[1]:.6f}\\paperwidth}}\n"
        f"\\setlength\\colCwidth{{{col_fracs[2]:.6f}\\paperwidth}}\n"
        "\\makeatother\n"
    )
    pos = tex.find(r"\begin{document}")
    return tex[:pos] + snippet + tex[pos:] if pos!=-1 else tex + snippet

# ---------- baposter ----------
def bump_baposter_fontscale(tex: str, target: float) -> str:
    def repl(m):
        opt = m.group(1)
        opt2 = re.sub(r"fontscale\s*=\s*[\d.]+", "", opt)
        opt2 = re.sub(r",,", ",", opt2).strip().strip(",")
        opt2 = (opt2 + "," if opt2 else "") + f"fontscale={target}"
        return f"\\documentclass[{opt2}]{{baposter}}"
    return re.sub(r"\\documentclass\[(.*?)\]\{baposter\}", repl, tex, flags=re.S)

def parse_brace_group(tex: str, start: int) -> tuple[int,int]:
    assert tex[start] == '{'
    depth = 0
    for i in range(start, len(tex)):
        if tex[i] == '{': depth += 1
        elif tex[i] == '}':
            depth -= 1
            if depth == 0: return start, i
    return start, start

def set_poster_option(tex: str, key: str, value: str) -> str:
    """在 \begin{poster}{...} 的第一个大括号里插入/替换 key=value。"""
    groups, _ = get_poster_args_ranges(tex)
    if not groups:
        return tex
    s, e = groups[0]  # 第1个 {} 就是 poster 的 options
    opts = tex[s+1:e]
    # 已有就替换；没有就附加
    pat = re.compile(rf'(?<!\w){re.escape(key)}\s*=\s*[^,}}]+')
    if pat.search(opts):
        opts2 = pat.sub(f"{key}={value}", opts)
    else:
        opts_stripped = opts.strip()
        sep = "" if not opts_stripped else ("," if opts_stripped.rstrip().endswith(",") else ",")
        opts2 = opts_stripped + f"{sep}\n{key}={value}"
    return tex[:s+1] + opts2 + tex[e:]

def enforce_baposter_three_columns(tex: str) -> str:
    """强制3列，并调小列间距以铺满页面宽度。"""
    tex = set_poster_option(tex, "columns", "3")
    tex = set_poster_option(tex, "colspacing", "0.6em")  # ← 从 1em 收紧到 0.6em
    return tex

def bump_baposter_margin(tex: str, margin_len: str = "7mm") -> str:
    """
    在 \documentclass[...,margin=<len>]{baposter} 里设置(或替换) margin=<len>。
    """
    def repl(m):
        opts = m.group(1)
        # 删除已有 margin=...
        opts2 = re.sub(r"(?<!\w)margin\s*=\s*[^,\]]+", "", opts)
        # 清理多余逗号
        opts2 = re.sub(r",,", ",", opts2).strip().strip(",")
        # 附加新的 margin
        opts2 = (opts2 + "," if opts2 else "") + f"margin={margin_len}"
        return f"\\documentclass[{opts2}]{{baposter}}"
    return re.sub(r"\\documentclass\[(.*?)\]\{baposter\}", repl, tex, flags=re.S)

def _soft_wrap_box_title(title: str, first_limit=28, next_limit=32) -> str:
    """
    把很长的 headerbox 标题按词边界软换行，返回带 '\\\\' 的字符串。
    """
    t = (title or "").strip()
    if len(t) <= first_limit:
        return t
    def break_at(s, limit):
        for sep in [": ", " - ", " — ", " – ", "· ", " "]:
            idx = s.rfind(sep, 0, limit+1)
            if idx != -1:
                return s[:idx+len(sep)].rstrip(), s[idx+len(sep):].lstrip()
        return s[:limit].rstrip(), s[limit:].lstrip()
    head, rest = break_at(t, first_limit)
    parts = [head]
    if rest:
        if len(rest) > next_limit:
            mid, tail = break_at(rest, next_limit); parts.append(mid)
            if tail: parts.append(tail)
        else:
            parts.append(rest)
    return r" \\ ".join(parts)

def get_poster_args_ranges(tex: str):
    m = re.search(r"\\begin\{poster\}", tex)
    if not m: return None, None
    i = m.end()
    while i < len(tex) and tex[i].isspace(): i += 1
    groups=[]
    for _ in range(5):
        while i < len(tex) and tex[i] != '{': i += 1
        if i>=len(tex): break
        s,e = parse_brace_group(tex, i); groups.append((s,e)); i = e+1
    if len(groups) < 5: return None, None
    insert_after = groups[-1][1] + 1
    return groups, insert_after

def rewrite_baposter_header(tex: str, title_wrapped: str, authors: str, affiliations: str) -> str:
    groups, _ = get_poster_args_ranges(tex)
    if not groups: return tex
    g3s,g3e = groups[2]
    g4s,g4e = groups[3]
    g5s,g5e = groups[4]
    br = title_wrapped.count("\\\\")
    tsize = "\\Huge " if br==0 else ("\\huge " if br==1 else "\\LARGE ")
    new_title_arg = "{\\bfseries " + tsize + "\\textsc{" + escape_text(title_wrapped) + "}" + "}"
    authors_affil = "\\textsc{" + escape_text(authors) + "}"
    if (affiliations or "").strip():
        authors_affil += r"\\ " + "\\textsc{" + escape_text(affiliations) + "}"
    new_authors_arg = "{" + authors_affil + "}"
    right_logo_path = OUTPUT_DIR / RIGHT_LOGO_FILENAME
    if right_logo_path.exists():
        new_right_arg = "{\\includegraphics[height=" + TITLE_EM_HEIGHT + "]{" + RIGHT_LOGO_FILENAME + "}}"
    else:
        new_right_arg = tex[g5s:g5e+1]
    new_tex = tex[:g3s] + new_title_arg + tex[g3e+1:g4s] + new_authors_arg + tex[g4e+1:g5s] + new_right_arg + tex[g5e+1:]
    return new_tex

def wipe_poster_body_and_insert(tex: str, body: str) -> str:
    groups, insert_after = get_poster_args_ranges(tex)
    if not groups: return tex
    pend = tex.find(r"\end{poster}", insert_after)
    if pend == -1: pend = len(tex)
    return tex[:insert_after] + "\n" + body + "\n" + tex[pend:]

def headerbox_text(title: str, name: str, opts: str, body: str) -> str:
    # 标题软换行 + 正确转义（逐行转义，保留换行符）
    wrapped = _soft_wrap_box_title(title)
    safe = " \\\\ ".join(escape_text(p) for p in wrapped.split(r" \\ "))
    return f"\\headerbox{{{safe}}}{{name={name},{opts}}}{{\n{body}\n}}\n\n"

# ---------- 内容 ----------
def format_content_to_latex(content: str) -> str:
    if not content: return ""
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if lines and all(ln.startswith(("-", "•")) for ln in lines):
        items = [escape_text(ln.lstrip("-• ").strip()) for ln in lines]
        return "\n".join(["\\begin{itemize}", "\\setlength{\\itemsep}{2pt}", "\\setlength{\\parsep}{0pt}"]
                         + [f"\\item {it}" for it in items] + ["\\end{itemize}"])
    return escape_text(" ".join(lines))

def build_header_from_meta(meta: dict):
    raw_title = meta.get('poster_title','') or ''
    wrapped_title = soft_wrap_title_for_logo(raw_title)
    a = meta.get('authors','') or ''
    inst = meta.get('affiliations','') or ''
    return wrapped_title, a, inst

# ---------- arrangement / captions / images ----------
def load_arrangement_and_captions():
    arr = json.loads(ARRANGEMENT_PATH.read_text(encoding="utf-8"))
    panels = arr.get("panel_arrangement", [])
    figures = arr.get("figure_arrangement", [])
    panels_by_id = {p["panel_id"]: p for p in panels if "panel_id" in p}
    cap_full, cap_base = {}, {}
    if CAPTION_PATH.exists():
        caps = json.loads(CAPTION_PATH.read_text(encoding="utf-8"))
        if isinstance(caps, dict):
            for _, v in caps.items():
                imgp = v.get("image_path", ""); cap = v.get("caption", "")
                if imgp:
                    cap_full[imgp] = cap
                    cap_base[os.path.basename(imgp)] = cap
    return panels_by_id, figures, cap_full, cap_base

def resolve_images_parent_dir(sample_paths):
    for parent in IMAGES_PARENTS:
        for sp in sample_paths[:10]:
            if sp:
                p = parent / sp
                if p.exists():
                    return parent
    return IMAGES_PARENTS[0]

def _fallback_search_by_basename(images_parent: pathlib.Path, basename: str) -> pathlib.Path | None:
    # 有限度搜索：只在 <parent>/<4o_4o>_images_and_tables/** 下找第一个同名文件
    root = images_parent / IMAGES_DIR_NAME
    if not root.exists(): return None
    try:
        for p in root.rglob(basename):
            if p.is_file(): return p
    except Exception:
        pass
    return None

def copy_and_get_relpath(figure_path: str, out_tex_path: pathlib.Path, images_parent: pathlib.Path) -> str:
    fig_dir = out_tex_path.parent / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    p = pathlib.Path(figure_path)
    if p.is_absolute():
        src = p
    else:
        if p.parts and p.parts[0] == IMAGES_DIR_NAME:
            src = images_parent / p
        else:
            src = images_parent / IMAGES_DIR_NAME / p
    if not src.exists():
        # 兜底：按 basename 搜索一次
        fb = _fallback_search_by_basename(images_parent, p.name)
        if fb is not None:
            src = fb
    dst = fig_dir / src.name
    try:
        if src.exists() and ((not dst.exists()) or src.stat().st_mtime > dst.stat().st_mtime):
            shutil.copy2(src, dst)
    except Exception:
        pass
    return str(pathlib.Path("figures") / dst.name).replace(os.sep, "/")

def build_figures_for_sections(sections, panels_by_id, figures, cap_full, cap_base):
    sec_name_to_idx = {norm_title(sec.get("title","")): i
                       for i, sec in enumerate(sections)
                       if norm_title(sec.get("title","")) != norm_title("Poster Title & Author")}
    panelid_to_secidx = {}
    for p in panels_by_id.values():
        pname = norm_title(p.get("panel_name",""))
        if pname in sec_name_to_idx:
            panelid_to_secidx[p["panel_id"]] = sec_name_to_idx[pname]
    sec_panel_height = {}; sec_arranged_fig_height = {}
    for pid, p in panels_by_id.items():
        if pid in panelid_to_secidx:
            sidx = panelid_to_secidx[pid]
            sec_panel_height[sidx] = float(p.get("height", 0.0) or 0.0)
            sec_arranged_fig_height[sidx] = 0.0
    sec_figs = {i: [] for i in range(len(sections))}
    for fg in figures:
        pid = fg.get("panel_id")
        if pid not in panelid_to_secidx: continue
        sidx = panelid_to_secidx[pid]
        pinfo = panels_by_id.get(pid, {})
        p_w = float(pinfo.get("width", 1.0) or 1.0)
        f_w = float(fg.get("width", 0.0) or 0.0)
        frac = 0.0 if p_w <= 0 else (f_w / p_w) * 0.95
        width_frac = max(FIG_MIN_FRAC, min(FIG_MAX_FRAC, (frac if frac>0 else 0.6)*FIG_ENLARGE_FACTOR))
        fpath = fg.get("figure_path", "")
        cap_raw = cap_full.get(fpath) or cap_base.get(os.path.basename(fpath)) or ""
        cap = clean_caption_prefix(cap_raw)
        sec_figs[sidx].append({
            "src": fpath, "caption": cap,
            "width_frac": width_frac,
            "order_y": float(fg.get("y", 0.0) or 0.0),
            "arranged_height": float(fg.get("height", 0.0) or 0.0)
        })
        sec_arranged_fig_height[sidx] = sec_arranged_fig_height.get(sidx, 0.0) + float(fg.get("height", 0.0) or 0.0)
    for i in list(sec_figs.keys()):
        sec_figs[i].sort(key=lambda x: x["order_y"])
    for sidx, figs in sec_figs.items():
        if not figs: continue
        panel_h = sec_panel_height.get(sidx, 0.0)
        arranged_h = sec_arranged_fig_height.get(sidx, 0.0)
        content = sections[sidx].get("content","") or ""
        n_chars = len(content.strip().replace("\n"," "))
        n_lines = math.ceil(n_chars / max(1, TEXT_CHAR_PER_LINE))
        text_ratio = n_lines * LINE_HEIGHT_WEIGHT
        ratio_limit = max(0.30, BASE_FIG_RATIO_LIMIT - min(0.25, 0.12 * (n_chars/600.0)))
        cur_ratio = 0.0 if panel_h <= 0 else arranged_h / panel_h
        safety = 0.08
        allowed = max(0.0, ratio_limit - text_ratio - safety)
        if cur_ratio > 0 and allowed > 0 and cur_ratio > allowed:
            scale = allowed / cur_ratio
            for it in figs:
                it["width_frac"] = max(FIG_MIN_FRAC, min(FIG_MAX_FRAC, it["width_frac"] * scale))
    return sec_figs

def figures_to_latex_beamer(fig_list, out_tex_path: pathlib.Path, images_parent: pathlib.Path) -> str:
    chunks=[]
    for it in fig_list:
        rel = copy_and_get_relpath(it["src"], out_tex_path, images_parent)
        w = it["width_frac"]; cap = escape_text(it["caption"] or "")
        chunks.append("\\begin{figure}\n\\centering\n"
                      f"\\includegraphics[width={w:.2f}\\linewidth]{{{rel}}}\n"
                      + (f"\\caption{{{cap}}}\n" if cap else "") + "\\end{figure}\n")
    return "\n".join(chunks)

def figures_to_latex_baposter(fig_list, out_tex_path: pathlib.Path, images_parent: pathlib.Path) -> str:
    chunks=[]
    for it in fig_list:
        rel = copy_and_get_relpath(it["src"], out_tex_path, images_parent)
        basename = os.path.basename(rel)  # 只写文件名
        w = max(0.90, min(0.98, it["width_frac"]))  # 稍微更大
        cap = escape_text(it["caption"] or "")
        chunks.append(
            "\\begin{center}\n"
            +f"\\includegraphics[width={w:.2f}\\linewidth]{{{basename}}}\n"
            + (f"\\captionof{{figure}}{{{cap}}}\n" if cap else "")
            +"\\vspace{-0.2em}\n"
            +"\\end{center}\n"
        )
    return "\n".join(chunks)

# ### NEW: 估算 section 占用（用于 baposter 溢出防护 & beamer 加权）
def _estimate_section_occupancy(section, figs_for_section):
    content = section.get("content","") or ""
    n_chars = len(content.strip().replace("\n"," "))
    n_lines = math.ceil(n_chars / max(1, TEXT_CHAR_PER_LINE))
    text_part = n_lines * LINE_HEIGHT_WEIGHT
    fig_part  = sum(max(0.45, min(0.85, it.get("width_frac", 0.7))) for it in figs_for_section)
    return text_part + fig_part

# ### NEW: beamer 自适应列宽（根据每列最长标题；不使用 span）
def _compute_beamer_col_fracs(sections, per_col_idxs, sep_frac=SEP_FRAC_DEFAULT):
    # 初始权重
    w = [1.0, 1.0, 1.0]
    # 找每列内最长标题
    longest = []
    for col, idxs in enumerate(per_col_idxs):
        if not idxs:
            longest.append(0)
            continue
        longest_title = max(len((sections[i].get("title") or "")) for i in idxs)
        longest.append(longest_title)
    # 给最长的那一列加权
    if longest:
        j = int(max(range(len(longest)), key=lambda k: longest[k] if len(longest)>0 else 0))
        if longest[j] >= LONG_TITLE_THRESHOLD:
            w[j] += W_HEAVY_BOOST
    total_w = sum(w) if sum(w)>0 else 3.0
    # 可用总宽（除去 4 个分隔列）
    usable = 1.0 - 4*sep_frac
    # 归一化并夹紧
    fracs = [max(COL_FRAC_MIN, min(COL_FRAC_MAX, usable * (wi/total_w))) for wi in w]
    # 可能因为夹紧导致和不等于 usable，再次归一化一次以严格填满
    s = sum(fracs)
    if s > 0:
        fracs = [fi * usable / s for fi in fracs]
    return fracs

# ### NEW: baposter 列占用超限时，统一缩放该列图宽，并有溢出则不加 above=bottom
def _rebalance_baposter(secidx_to_figs, sections, per_col_idxs, max_occupancy=0.98):
    col_occupancies = []
    for col, idxs in enumerate(per_col_idxs):
        occ = 0.0
        for sidx in idxs:
            figs = secidx_to_figs.get(sidx, [])
            occ += _estimate_section_occupancy(sections[sidx], figs)
        col_occupancies.append(occ)

    # 对占用超限的列，按比例缩放图片宽度
    for col, (occ, idxs) in enumerate(zip(col_occupancies, per_col_idxs)):
        if occ > max_occupancy and occ > 0:
            scale = max(0.80, min(0.97, max_occupancy / occ))
            for sidx in idxs:
                for it in secidx_to_figs.get(sidx, []):
                    it["width_frac"] = max(FIG_MIN_FRAC, min(FIG_MAX_FRAC, it["width_frac"] * scale))

    # 返回每列是否允许 bottom 对齐（占用安全才允许）
    allow_bottom = [occ <= max_occupancy for occ in col_occupancies]
    return allow_bottom

# ---------- 主流程 ----------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    meta = data.get("meta", {}) or {}
    secs_all = data.get("sections", []) or []
    sections = [s for s in secs_all if norm_title(s.get("title","")) != norm_title("Poster Title & Author")]

    panels_by_id, figures, cap_full, cap_base = load_arrangement_and_captions()
    sample_paths = [pathlib.Path(f.get("figure_path","")) for f in figures if f.get("figure_path")]
    images_parent = resolve_images_parent_dir(sample_paths)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    mode = detect_template(template)
    wrapped_title, authors, affiliations = build_header_from_meta(meta)

    if mode == "beamer":
        new_tex = replace_command_balanced(template, "title", f"\\title{{{escape_text(wrapped_title)}}}")
        new_tex = replace_command_balanced(new_tex, "author", f"\\author{{{escape_text(authors)}}}")
        new_tex = replace_command_balanced(new_tex, "institute", f"\\institute[shortinst]{{{escape_text(affiliations)}}}")
        new_tex = bump_beamerposter_scale(new_tex, BEAMER_SCALE_TARGET)
        new_tex = inject_font_tweaks_beamer(new_tex, choose_title_size_cmd(wrapped_title))
        new_tex = inject_right_logo_beamer(new_tex)

        secidx_to_figs = build_figures_for_sections(sections, panels_by_id, figures, cap_full, cap_base)
        blocks=[]
        for i, sec in enumerate(sections):
            figs_tex = figures_to_latex_beamer(secidx_to_figs.get(i, []), OUTPUT_PATH, images_parent) if secidx_to_figs.get(i) else ""
            body = format_content_to_latex(sec.get("content",""))
            if figs_tex: body = (body + "\n\n" if body else "") + figs_tex
            blocks.append(f"\\begin{{block}}{{{escape_text(sec.get('title',''))}}}\n{body}\n\\end{{block}}\n")

        pos_doc = new_tex.find(r"\begin{document}")
        if pos_doc == -1: raise RuntimeError("未找到 \\begin{document}")
        b,e = find_env_bounds(new_tex, "columns", pos_doc)
        if b is None: raise RuntimeError("未在文档主体找到 \\begin{columns} ... \\end{columns}")
        region = new_tex[b:e]
        begin_tok = extract_begin_token_with_options(region, "columns")
        per_col_blocks = split_even_continuous(blocks, 3)

        # ### NEW: 计算自适应列宽，并注入固定长度，避免整体偏左
        col_fracs = _compute_beamer_col_fracs(sections, [list(range(len(x))) for x in split_even_continuous(list(range(len(sections))), 3)], sep_frac=SEP_FRAC_DEFAULT)
        new_tex = inject_beamer_column_widths(new_tex, col_fracs, SEP_FRAC_DEFAULT)

        # ### NEW: 显式插入分隔列（\sepwidth）与三列具体宽度（\colA/B/Cwidth），严格填满
        body_lines=[]
        # leading separator
        body_lines.append(r"\begin{column}{\sepwidth}\end{column}")
        colw_macros = [r"\colAwidth", r"\colBwidth", r"\colCwidth"]
        for i in range(3):
            body_lines.append(r"\begin{column}{\sepwidth}\end{column}")
            body_lines.append(fr"\begin{{column}}{{{colw_macros[i]}}}")
            if per_col_blocks[i]: body_lines.append("\n".join(per_col_blocks[i]))
            body_lines.append(r"\end{column}")
        # trailing separator
        body_lines.append(r"\begin{column}{\sepwidth}\end{column}")

        columns_new = begin_tok + "\n" + "\n".join(body_lines) + "\n\\end{columns}"
        new_tex = new_tex[:b] + columns_new + new_tex[e:]

    else:
        # --- baposter ---
        new_tex = bump_baposter_fontscale(template, BAPOSTER_FONTSCALE_TARGET)

        # 把页面边距压小，让三列更“铺满”
        new_tex = bump_baposter_margin(new_tex, "7mm")   # 你也可以试 "5mm" 或 "10mm"

        new_tex = rewrite_baposter_header(new_tex, wrapped_title, authors, affiliations)
        new_tex = enforce_baposter_three_columns(new_tex)

        # 3 列均匀 + 列底对齐（带溢出防护）
        per_col_idxs = split_even_continuous(list(range(len(sections))), 3)
        secidx_to_figs = build_figures_for_sections(sections, panels_by_id, figures, cap_full, cap_base)

        # ### NEW: 根据每列估算占用，必要时缩放图宽，且仅在安全时对最后一个 headerbox 使用 above=bottom
        allow_bottom = _rebalance_baposter(secidx_to_figs, sections, per_col_idxs, max_occupancy=0.98)

        bodies = []
        for i, sec in enumerate(sections):
            figs_tex = figures_to_latex_baposter(secidx_to_figs.get(i, []), OUTPUT_PATH, images_parent) if secidx_to_figs.get(i) else ""
            bodies.append(format_content_to_latex(sec.get("content","")) + ("\n\n"+figs_tex if figs_tex else ""))

        hb_parts=[]; used=set(); prev={0:None,1:None,2:None}
        for col, idxs in enumerate(per_col_idxs):
            for j, sidx in enumerate(idxs):
                title = sections[sidx].get("title","") or f"Section {sidx+1}"
                base = slug_name(title); name = base; k=1
                while name in used: k+=1; name=f"{base}{k}"
                used.add(name)
                is_first = (prev[col] is None)
                is_last  = (j == len(idxs)-1)
                if is_first:
                    opts = f"column={col},row=0,span=1"
                else:
                    opts = f"column={col},below={prev[col]},span=1"
                # 仅当该列估算占用安全时，才将最后一个 box 固定到底部，避免溢出重叠
                if is_last and allow_bottom[col]:
                    opts += ",above=bottom"
                hb_parts.append(headerbox_text(title, name, opts, bodies[sidx]))
                prev[col] = name

        body_all = "\n".join(hb_parts)
        new_tex = wipe_poster_body_and_insert(new_tex, body_all)

    OUTPUT_PATH.write_text(new_tex, encoding="utf-8")
    print(f"✅ Wrote: {OUTPUT_PATH.relative_to(ROOT_DIR)}")
    print(f"📁 Figures copied to: {OUTPUT_DIR / 'figures'}")
    print(f"🧩 Template detected: {mode}")

if __name__ == "__main__":
    main()

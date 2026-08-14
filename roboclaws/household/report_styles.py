from __future__ import annotations

from roboclaws.core.rerun import rerun_panel_css


def report_css(*, extra_css: str = "") -> str:
    extra_css_block = f"{extra_css.rstrip()}\n" if extra_css else ""
    return f"""    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      color: #20242c;
      background: #eef2f6;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 48px; }}
    h1 {{ font-size: 30px; margin: 0; letter-spacing: 0; }}
    h2 {{ font-size: 19px; margin: 0 0 12px; letter-spacing: 0; }}
    h2 span {{ color: #647083; font-size: 13px; font-weight: 650; }}
    .summary {{
      background: #20242c;
      color: #f8fafc;
      border-radius: 8px;
      padding: 22px;
      box-shadow: 0 14px 34px rgba(25, 32, 44, 0.16);
    }}
    .summary-head {{ display: flex; justify-content: space-between; gap: 16px; align-items: end; }}
    .summary-metadata {{
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 8px;
      margin-top: 12px;
      background: rgba(255, 255, 255, 0.05);
    }}
    .summary-metadata > summary {{
      min-height: 42px;
      padding: 10px 12px;
      cursor: pointer;
      color: #dbe5ef;
      font-weight: 750;
    }}
    .summary-metadata .badges {{ padding: 0 12px 12px; }}
    .summary-alert {{
      display: grid;
      gap: 6px;
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 8px;
      margin: 0 0 12px;
      padding: 12px;
      background: rgba(255, 255, 255, 0.07);
    }}
    .summary-alert strong {{
      color: #ffffff;
      font-size: 14px;
    }}
    .summary-alert p {{
      margin: 0;
      color: #dbe5ef;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }}
    .summary-alert-failure {{
      border-color: rgba(248, 113, 113, 0.44);
      background: rgba(127, 29, 29, 0.28);
    }}
    .eyebrow {{
      margin: 0 0 6px;
      color: #a7d8cf;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin: 18px 0;
    }}
    .metric {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 8px;
      padding: 12px;
    }}
    .metric span {{ display: block; color: #b7c1ce; font-size: 12px; margin-bottom: 4px; }}
    .metric strong {{
      display: block;
      color: #ffffff;
      font-size: 19px;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }}
    .panel .metric {{
      background: #f8fafc;
      border-color: #d9dde6;
    }}
    .panel .metric span {{ color: #647083; }}
    .panel .metric strong {{ color: #20242c; }}
    .panel {{
      background: #ffffff;
      border: 1px solid #d8dee8;
      border-radius: 8px;
      padding: 18px;
      margin-top: 18px;
      box-shadow: 0 5px 16px rgba(25, 32, 44, 0.06);
    }}
    .report-tabs {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      gap: 8px;
      overflow-x: auto;
      margin-top: 18px;
      padding: 10px;
      background: rgba(238, 242, 246, 0.96);
      border: 1px solid #d8dee8;
      border-radius: 8px;
      backdrop-filter: blur(8px);
    }}
    .report-tab {{
      min-height: 40px;
      border: 1px solid #cfd6e2;
      border-radius: 6px;
      padding: 0 12px;
      background: #ffffff;
      color: #334155;
      font: inherit;
      font-size: 14px;
      font-weight: 700;
      white-space: nowrap;
      cursor: pointer;
    }}
    .report-tab[aria-selected="true"] {{
      background: #20242c;
      border-color: #20242c;
      color: #ffffff;
    }}
    .report-tab:focus-visible {{
      outline: 3px solid #7cc7bb;
      outline-offset: 2px;
    }}
    .report-tab-panel {{ scroll-margin-top: 80px; }}
    .note-panel {{ background: #fbfcfd; }}
    .empty-state {{
      border: 1px dashed #cbd5e1;
      border-radius: 8px;
      background: #f8fafc;
      padding: 18px;
    }}
    .empty-state h3 {{ margin: 0 0 6px; color: #20242c; }}
    .empty-state p {{ margin: 0; color: #647083; max-width: 720px; }}
    .badges {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .badge {{
      background: #fff;
      border: 1px solid #d9dde6;
      border-radius: 6px;
      padding: 7px 10px;
    }}
    .summary .badge {{
      background: rgba(255, 255, 255, 0.09);
      border-color: rgba(255, 255, 255, 0.18);
      color: #e9edf4;
    }}
    .summary .badge strong {{ color: #ffffff; }}
    .snapshots {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }}
    .before-after-section .snapshots figcaption,
    .comparison-item figcaption,
    .nav2-preview figcaption {{
      display: grid;
      gap: 3px;
    }}
    figcaption strong {{ color: #20242c; }}
    figcaption span {{ color: #647083; font-size: 12px; }}
    .comparison-details,
    .timing-details,
    .artifact-details,
    .robot-timeline-details {{
      margin-top: 14px;
      border: 1px solid #d9dde6;
      border-radius: 8px;
      background: #fbfcfd;
    }}
    .comparison-details > summary,
    .timing-details > summary,
    .artifact-details > summary,
    .robot-timeline-details > summary {{
      min-height: 44px;
      padding: 12px 14px;
      cursor: pointer;
      font-weight: 750;
    }}
    .comparison-details > summary span {{
      color: #647083;
      font-size: 13px;
      font-weight: 650;
      margin-left: 8px;
    }}
    .comparison-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 12px;
      padding: 0 12px 12px;
    }}
    .comparison-item {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #ffffff;
    }}
    .comparison-item summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 24px;
      gap: 10px;
      align-items: start;
      min-height: 58px;
      list-style: none;
      cursor: pointer;
    }}
    .comparison-item summary::-webkit-details-marker {{ display: none; }}
    .comparison-item summary::after {{
      content: "-";
      width: 24px;
      height: 24px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: #e6eef5;
      color: #334155;
      font-weight: 800;
    }}
    .comparison-item:not([open]) summary::after {{ content: "+"; }}
    .comparison-item[open] summary {{ margin-bottom: 10px; }}
    .comparison-item-head {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .comparison-item-head strong {{ font-size: 15px; overflow-wrap: anywhere; }}
    .comparison-item-head span {{
      color: #647083;
      font-size: 12px;
      overflow-wrap: anywhere;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      overflow: hidden;
    }}
    .comparison-views {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 8px;
    }}
    .comparison-missing {{
      display: grid;
      min-height: 120px;
      place-items: center;
      background: #f1f5f9;
    }}
    figure {{
      margin: 0;
      background: #fff;
      border: 1px solid #d9dde6;
      border-radius: 6px;
      padding: 10px;
    }}
    img {{ width: 100%; height: auto; display: block; }}
    .image-link {{
      position: relative;
      display: block;
      border-radius: 4px;
      overflow: hidden;
      cursor: zoom-in;
    }}
    .image-link::after {{
      content: "+";
      position: absolute;
      top: 8px;
      right: 8px;
      width: 26px;
      height: 26px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: rgba(32, 36, 44, 0.82);
      color: #ffffff;
      font-size: 18px;
      font-weight: 800;
      opacity: 0;
      transform: scale(0.94);
      transition: opacity 0.16s ease, transform 0.16s ease;
    }}
    .image-link:hover::after,
    .image-link:focus-visible::after {{
      opacity: 1;
      transform: scale(1);
    }}
    .image-link:focus-visible {{
      outline: 3px solid #7cc7bb;
      outline-offset: 3px;
    }}
    .image-lightbox[hidden] {{ display: none; }}
    .image-lightbox {{
      position: fixed;
      inset: 0;
      z-index: 1000;
      display: grid;
      place-items: center;
      padding: 24px;
      background: rgba(12, 16, 24, 0.86);
    }}
    .lightbox-dialog {{
      display: grid;
      gap: 10px;
      max-width: min(96vw, 1440px);
      max-height: 92vh;
      color: #f8fafc;
    }}
    .lightbox-dialog img {{
      max-width: min(96vw, 1440px);
      max-height: 82vh;
      width: auto;
      height: auto;
      object-fit: contain;
      border-radius: 6px;
      background: #0f172a;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.42);
    }}
    .lightbox-caption {{
      margin: 0;
      color: #e2e8f0;
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .lightbox-close {{
      position: fixed;
      top: 18px;
      right: 18px;
      min-height: 38px;
      border: 1px solid rgba(255, 255, 255, 0.22);
      border-radius: 6px;
      padding: 0 12px;
      background: rgba(15, 23, 42, 0.88);
      color: #ffffff;
      font: inherit;
      font-weight: 750;
      cursor: pointer;
    }}
    .lightbox-close:focus-visible {{
      outline: 3px solid #7cc7bb;
      outline-offset: 2px;
    }}
    figcaption {{ margin-top: 8px; color: #565f70; font-size: 14px; }}
    .note {{ color: #565f70; margin: 0 0 12px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #d9dde6; border-radius: 8px; }}
    .timing-lane-block {{
      margin: 14px 0;
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .timing-lane-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
    }}
    .timing-lane-head h3 {{ margin: 0; font-size: 15px; }}
    .timing-lane-head span {{ color: #475569; font-weight: 750; }}
    .timing-lane {{
      display: flex;
      gap: 3px;
      overflow-x: auto;
      padding-bottom: 2px;
    }}
    .timing-segment {{
      flex: 0 0 max(var(--basis), 104px);
      min-height: 74px;
      display: grid;
      align-content: center;
      gap: 3px;
      padding: 10px;
      color: #ffffff;
      background: var(--segment-color);
      border-radius: 6px;
    }}
    .timing-segment strong,
    .timing-segment span,
    .timing-segment small {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .timing-segment span {{ font-size: 16px; font-weight: 800; }}
    .timing-segment small {{ color: rgba(255, 255, 255, 0.82); }}
    .timing-details .table-wrap,
    .artifact-details .table-wrap {{ margin: 0 12px 12px; }}
    .object-cycle-timing {{
      margin-top: 16px;
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .object-cycle-timing > h3 {{ margin: 0 0 8px; font-size: 16px; }}
    .object-cycle-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }}
    .object-cycle {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #ffffff;
    }}
    .object-cycle h3 {{ margin: 0 0 8px; font-size: 15px; overflow-wrap: anywhere; }}
    .object-cycle .timing-lane-block {{ margin: 0; padding: 10px; }}
    .object-cycle p {{ margin: 8px 0 0; color: #565f70; font-size: 12px; overflow-wrap: anywhere; }}
    .robot-timeline-details .robot-step {{
      margin: 0 12px 12px;
    }}
    .robot-step {{
      background: #fff;
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 14px;
    }}
    .robot-step h3 {{ font-size: 16px; margin: 0 0 4px; }}
    .pose {{ margin: 0 0 10px; color: #565f70; font-size: 13px; }}
    .semantic-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }}
    .semantic-badges .badge {{ font-size: 13px; padding: 5px 8px; background: #eef6ff; }}
    .focus-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }}
    .focus-badges .badge {{ font-size: 13px; padding: 5px 8px; }}
    .action-evidence-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: -2px 0 10px; }}
    .action-evidence-badges .badge {{
      font-size: 12px; padding: 4px 7px; background: #fff7ed; border-color: #fed7aa;
    }}
    .action-evidence-note {{ margin-top: -4px; }}
    .evidence-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: -4px 0 10px; }}
    .evidence-badges .badge {{ font-size: 12px; padding: 4px 7px; background: #f8fafc; }}
    .views {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 10px;
    }}
    .robot-primary-views {{
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    }}
    .sim-only-views {{
      margin-top: 10px;
      border: 1px dashed #cbd5e1;
      border-radius: 8px;
      background: #f8fafc;
    }}
    .sim-only-views > summary {{
      min-height: 40px;
      padding: 10px 12px;
      cursor: pointer;
      color: #475569;
      font-weight: 750;
    }}
    .sim-only-views .views {{ padding: 0 12px 12px; }}
    .sim-only-grid-single {{
      grid-template-columns: minmax(0, min(100%, 560px));
      justify-content: start;
    }}
{extra_css_block}    .raw-fpv-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
    }}
    .raw-fpv-card {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .raw-fpv-card h3 {{ margin: 0 0 4px; font-size: 15px; }}
    .raw-fpv-card figure {{ margin-top: 10px; }}
    .semantic-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }}
    .semantic-card {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .semantic-card summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto 24px;
      gap: 10px;
      align-items: center;
      list-style: none;
      cursor: pointer;
    }}
    .semantic-card summary::-webkit-details-marker {{ display: none; }}
    .semantic-card summary::after {{
      content: "+";
      width: 24px;
      height: 24px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: #e6eef5;
      color: #334155;
      font-weight: 800;
    }}
    .semantic-card[open] summary {{ margin-bottom: 10px; }}
    .semantic-card[open] summary::after {{ content: "-"; }}
    .semantic-card-head {{
      display: grid;
      gap: 4px;
      margin: 0;
      min-width: 0;
    }}
    .semantic-card-head strong {{
      overflow-wrap: anywhere;
      font-size: 14px;
    }}
    .semantic-card-head span {{
      color: #647083;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .semantic-card-status {{
      color: #475569;
      font-size: 12px;
      font-weight: 750;
      white-space: nowrap;
    }}
    .phase-rail {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(58px, 1fr));
      gap: 8px;
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .phase-rail li {{
      border: 1px solid #bfdcd7;
      background: #eef8f6;
      border-radius: 7px;
      padding: 8px 6px;
      text-align: center;
    }}
    .phase-rail span {{ display: block; font-weight: 750; color: #1f5f58; }}
    .phase-rail small {{ display: block; margin-top: 2px; color: #687789; }}
    .command-phase-rail {{ min-width: 280px; }}
    .readback {{ margin: 10px 0 0; color: #565f70; font-size: 13px; overflow-wrap: anywhere; }}
    .nav2-explainer {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .nav2-explainer div {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .nav2-explainer strong {{ display: block; margin-bottom: 4px; }}
    .nav2-explainer span {{ color: #565f70; }}
    .nav2-preview-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(220px, 300px);
      gap: 12px;
      align-items: start;
    }}
    .nav2-legend {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .nav2-legend h3 {{ margin: 0 0 10px; font-size: 15px; }}
    .nav2-legend ul {{ display: grid; gap: 10px; list-style: none; padding: 0; margin: 0; }}
    .nav2-legend li {{
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
    }}
    .nav2-legend small {{
      grid-column: 2;
      color: #647083;
    }}
    .legend-swatch {{
      width: 16px;
      height: 16px;
      border-radius: 4px;
      border: 1px solid #94a3b8;
      background: #e8eef6;
    }}
    .legend-swatch.fixture {{ background: #717c8d; border-color: #475569; }}
    .legend-swatch.waypoint {{ border-radius: 999px; background: #23865a; border-color: #23865a; }}
    .legend-swatch.robot {{ border-radius: 999px; background: #2e58b2; border-color: #1e4082; }}
    .nav2-legend p {{ margin: 12px 0 0; color: #565f70; }}
    .requirements {{ color: #565f70; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{
      padding: 9px 10px;
      text-align: left;
      border-bottom: 1px solid #e5e8ee;
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    th {{ background: #eef1f5; font-weight: 650; }}
    @media (max-width: 640px) {{
      main {{ padding: 18px 12px 36px; }}
      .summary-head,
      .timing-lane-head {{
        display: grid;
        align-items: start;
      }}
      .semantic-card summary {{
        grid-template-columns: minmax(0, 1fr) 24px;
      }}
      .semantic-card-status {{
        grid-column: 1 / -1;
      }}
      .nav2-preview-layout {{
        grid-template-columns: 1fr;
      }}
    }}
{rerun_panel_css()}
"""


def planner_report_css() -> str:
    return """    .diagnostic-view {
      background: #ffffff;
    }
    .diagnostic-visual {
      border-radius: 8px;
      overflow: hidden;
      background: #f8fafc;
    }
    .diagnostic-visual svg {
      width: 100%;
      height: auto;
      display: block;
    }
    .diagnostic-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .diagnostic-stat {
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 8px;
      background: #f8fafc;
    }
    .diagnostic-stat small {
      display: block;
      color: #64748b;
      margin-bottom: 3px;
    }
    .diagnostic-stat strong {
      color: #0f172a;
    }
    .post-placement-rejection-views h3 {
      margin: 14px 0 8px;
      font-size: 15px;
    }
    .rejection-view .diagnostic-visual {
      background: #fff7ed;
    }
    .grasp-blocker-matrix {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .grasp-blocker-card {
      border: 1px solid #fecaca;
      border-radius: 8px;
      padding: 12px;
      background: #fff7f7;
    }
    .grasp-blocker-route {
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 8px;
      align-items: center;
      margin-bottom: 8px;
    }
    .grasp-blocker-route strong {
      overflow-wrap: anywhere;
    }
    .grasp-blocker-route span {
      color: #64748b;
      font-size: 12px;
    }
    .grasp-blocker-card p {
      margin: 8px 0 0;
      color: #475569;
    }
    .decision-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin: 0 0 12px;
    }
    .decision-card {
      border: 1px solid #bfdbfe;
      border-radius: 8px;
      padding: 12px;
      background: #eff6ff;
    }
    .decision-card h3 { margin: 0 0 6px; font-size: 14px; color: #1e3a8a; }
    .decision-card strong {
      display: block;
      color: #0f172a;
      overflow-wrap: anywhere;
      margin-bottom: 8px;
    }
    .decision-card p { margin: 0; color: #475569; }
"""

const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let report=null, sources=null;
const sourceIds={student:"srcStudent",interview:"srcInterview",assignment:"srcAssignment",assessment:"srcAssessment",attendance:"srcAttendance"};
const ACCENT="#5c1a4a", WARN="#8a5a12", DANGER="#9b2c3a", MUTED="#6b6b6b", TRACK="#e6e6e6", INK="#0a0a0a", ACCENT_SOFT="#d4a5c4", WARN_SOFT="#e8d4a8";
const chartInstances={};
const DEPT_AVG = 72;
const TRAIT_MAP = {
  "excellent":10, "very good":8, "good":7, "average":5,
  "needs improvement":3, "poor":2, "fair":4, "strong":8
};

function esc(v){return String(v??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));}
function setText(id,v){const e=$("#"+id);if(e)e.textContent=v??"—";}
function pct(v){return `${Number(v||0).toFixed(v%1?1:0)}%`;}
function sevClass(s){return s==="critical"?"sev-critical":s==="moderate"?"sev-moderate":"sev-mild";}

function destroyChart(id){
  if(chartInstances[id]){chartInstances[id].destroy(); delete chartInstances[id];}
}

function topicAverages(questions){
  const buckets={};
  (questions||[]).forEach(q=>{
    const t=q.topic||"General";
    (buckets[t]||=[]).push(Number(q.score)||0);
  });
  return Object.entries(buckets)
    .map(([topic,scores])=>({topic, avg: +(scores.reduce((a,b)=>a+b,0)/scores.length).toFixed(2), n: scores.length}))
    .sort((a,b)=>a.avg-b.avg);
}

function barColor(v, max=100){
  const t=v/max;
  if(t>=0.85) return "#5c1a4a";
  if(t>=0.7) return "#8b3a72";
  if(t>=0.55) return "#8a5a12";
  return "#9b2c3a";
}

function makeChart(id, config){
  destroyChart(id);
  const canvas=$("#"+id);
  if(!canvas || typeof Chart==="undefined") return;
  chartInstances[id]=new Chart(canvas.getContext("2d"), config);
}

function drawCharts(r){
  if(typeof Chart==="undefined") return;
  Chart.defaults.font.family="'IBM Plex Sans', sans-serif";
  Chart.defaults.color=MUTED;
  Chart.defaults.borderColor=TRACK;

  const dims=r.dimension_scores||[];
  const qs=r.interview_deep_dive?.questions||[];
  const topics=topicAverages(qs);
  const lags=r.lagging_areas||[];
  const a=r.academic_snapshot;
  const att=r.attendance_snapshot;
  const iv=r.interview_deep_dive;
  const items=a.items||[];

  setText("chartSource", `${r.student_name} · ${r.student_id}`);
  setText("chartIntro",
    `Built from ${dims.length} dimension scores, ${qs.length} interview answers ` +
    `(${topics.length} topics), ${items.length} academic item(s), attendance ${att.percentage.toFixed(1)}%, ` +
    `and ${lags.length} lagging area(s). Composite ${r.overall_performance.score.toFixed(1)}.`
  );
  setText("dimChartCaption", `${dims.length} KPIs · 0–100`);
  setText("qChartCaption", `${qs.length} answers → ${topics.length} topics · /10`);
  setText("lagChartCaption", lags.length ? `${lags.length} area(s) below target` : "all at/above target");
  setText("kpiChartCaption", `weights × ${r.student_name}'s actuals`);
  setText("acadChartCaption", `${items.length} scored item(s) from assignment + assessment JSON`);

  // 1) Dimension scores — real KPI names + scores + dept benchmark
  makeChart("dimChart", {
    type: "bar",
    data: {
      labels: dims.map(d=>d.name),
      datasets: [
        {
          label: "Student score %",
          data: dims.map(d=>+Number(d.score).toFixed(1)),
          backgroundColor: dims.map(d=>barColor(d.score)),
          borderWidth: 0,
          borderRadius: 0,
          barThickness: 14
        },
        {
          label: "Dept avg (AIML) 72",
          data: dims.map(()=>DEPT_AVG),
          backgroundColor: "rgba(107,119,136,0.28)",
          borderWidth: 0,
          borderRadius: 0,
          barThickness: 14
        }
      ]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {position:"top", align:"end", labels:{boxWidth:12, font:{size:10}}},
        tooltip: {
          callbacks: {
            afterLabel: (ctx)=>{
              if(ctx.datasetIndex!==0) return "";
              const d=dims[ctx.dataIndex];
              const delta = d ? (d.score - DEPT_AVG).toFixed(1) : "";
              return d ? `Band: ${d.band} · vs dept: ${delta>=0?"+":""}${delta}` : "";
            }
          }
        }
      },
      scales: {
        x: {min:0, max:100, title:{display:true, text:"Score (0–100)"}, grid:{color:TRACK}},
        y: {grid:{display:false}}
      }
    }
  });

  // 2) Interview topic averages — aggregated from real question scores
  makeChart("qChart", {
    type: "bar",
    data: {
      labels: topics.map(t=>t.topic),
      datasets: [{
        label: "Topic average / 10",
        data: topics.map(t=>t.avg),
        backgroundColor: topics.map(t=>barColor(t.avg*10)),
        borderWidth: 0,
        borderRadius: 0,
        barThickness: 22
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {display:false},
        tooltip: {
          callbacks: {
            afterLabel: (ctx)=>{
              const t=topics[ctx.dataIndex];
              return t ? `${t.n} question(s) on transcript` : "";
            }
          }
        }
      },
      scales: {
        y: {min:0, max:10, ticks:{stepSize:1}, title:{display:true, text:"Average score / 10"}, grid:{color:TRACK}},
        x: {
          ticks: {maxRotation:45, minRotation:30, autoSkip:false, font:{size:10}},
          grid:{display:false}
        }
      }
    }
  });

  // 3) Current vs target for lagging areas (or all dimensions if none lagging)
  const compare = lags.length
    ? lags.map(a=>({label:a.area, current:a.current_score, target:a.target_score}))
    : dims.map(d=>({label:d.name, current:d.score, target:80}));

  makeChart("lagChart", {
    type: "bar",
    data: {
      labels: compare.map(c=>c.label),
      datasets: [
        {
          label: "Current",
          data: compare.map(c=>+Number(c.current).toFixed(1)),
          backgroundColor: WARN,
          borderWidth: 0,
          borderRadius: 0
        },
        {
          label: "Target",
          data: compare.map(c=>+Number(c.target).toFixed(1)),
          backgroundColor: ACCENT_SOFT,
          borderWidth: 0,
          borderRadius: 0
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {position:"top", align:"end", labels:{boxWidth:12, font:{size:11}}},
        tooltip: {
          callbacks: {
            afterBody: (items)=>{
              if(!items.length) return "";
              const i=items[0].dataIndex;
              const gap=+(compare[i].target-compare[i].current).toFixed(1);
              return gap>0 ? `Gap: ${gap} points` : "At or above target";
            }
          }
        }
      },
      scales: {
        y: {min:0, max:100, title:{display:true, text:"Score"}, grid:{color:TRACK}},
        x: {
          ticks: {maxRotation:40, minRotation:20, font:{size:10}},
          grid:{display:false}
        }
      }
    }
  });

  // 4) Weighted composition — pipeline formula with THIS student's actuals
  // Weights: interview 40%, assignments 30%, assessments 20%, attendance 10%
  const parts = [
    {label:"Interview (40%)", raw: iv.overall_score*10, weight:0.40, value: +(iv.overall_score*10*0.40).toFixed(2)},
    {label:"Assignments (30%)", raw: a.assignment_average, weight:0.30, value: +(a.assignment_average*0.30).toFixed(2)},
    {label:"Assessments (20%)", raw: a.assessment_average, weight:0.20, value: +(a.assessment_average*0.20).toFixed(2)},
    {label:"Attendance (10%)", raw: att.percentage, weight:0.10, value: +(att.percentage*0.10).toFixed(2)}
  ];

  makeChart("kpiChart", {
    type: "doughnut",
    data: {
      labels: parts.map(p=>`${p.label} · ${p.raw.toFixed(1)} → +${p.value}`),
      datasets: [{
        data: parts.map(p=>p.value),
        backgroundColor: ["#5c1a4a", "#8b3a72", "#2a2a2a", "#a0a0a0"],
        borderWidth: 2,
        borderColor: "#f7f8f9"
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {position:"right", labels:{boxWidth:12, font:{size:11}, padding:12}},
        tooltip: {
          callbacks: {
            label: (ctx)=>{
              const p=parts[ctx.dataIndex];
              return ` ${p.raw.toFixed(1)} × ${(p.weight*100).toFixed(0)}% = ${p.value} pts toward composite`;
            },
            footer: ()=>`Composite: ${r.overall_performance.score.toFixed(2)}`
          }
        }
      }
    }
  });

  // 5) Academic items — actual assignment/assessment percentages from sources
  const acadLabels = items.length
    ? items.map(i=>i.title.length>28 ? i.title.slice(0,26)+"…" : i.title)
    : ["No academic items"];
  const acadData = items.length ? items.map(i=>+Number(i.percent).toFixed(1)) : [0];

  makeChart("acadChart", {
    type: "bar",
    data: {
      labels: acadLabels,
      datasets: [{
        label: "Percent",
        data: acadData,
        backgroundColor: acadData.map(v=>barColor(v)),
        borderWidth: 0,
        borderRadius: 0,
        barThickness: items.length<=4 ? 36 : 22
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {display:false},
        tooltip: {
          callbacks: {
            afterLabel: (ctx)=>{
              const it=items[ctx.dataIndex];
              return it ? `${it.subject} · ${it.id}` : "";
            }
          }
        }
      },
      scales: {
        y: {min:0, max:100, title:{display:true, text:"Marks %"}, grid:{color:TRACK}},
        x: {grid:{display:false}, ticks:{font:{size:11}}}
      }
    }
  });
}

function renderTier(t){
  if(!t)return;
  setText("tierNum",`T${t.tier}`);
  setText("tierLabel",t.label);
  setText("tierTitle",t.title);
  setText("tierBand",t.score_band);
  setText("tierNarrative",t.narrative);
  const badge=$("#tierBadge");
  if(badge){
    badge.dataset.tier=String(t.tier);
    badge.className=`tier-badge tier-${t.tier}`;
  }
}

function renderLagging(areas){
  const el=$("#laggingAreas"); if(!el)return;
  if(!areas?.length){el.innerHTML="<p class='muted'>No lagging areas flagged.</p>";return;}
  el.innerHTML=areas.map(a=>`
    <div class="lag-item ${sevClass(a.severity)}">
      <div class="lag-top">
        <strong>${esc(a.area)}</strong>
        <span class="sev">${esc(a.severity)}</span>
      </div>
      <div class="lag-scores">
        <span>Now <b>${Math.round(a.current_score)}</b></span>
        <span>Target <b>${Math.round(a.target_score)}</b></span>
        <span>Gap <b>${Math.round(a.gap)}</b></span>
      </div>
      <div class="gap-track"><i style="width:${Math.min(100,a.gap)}%"></i></div>
      <p>${esc(a.evidence)}</p>
      <small>${esc(a.fix_hint)}</small>
    </div>`).join("");
}

function renderWeakness(w){
  if(!w)return;
  setText("weaknessSummary",w.summary);
  setText("weaknessPattern",w.pattern);
  setText("primaryWeakness",w.primary_weakness);
  const el=$("#weaknessItems"); if(!el)return;
  el.innerHTML=(w.items||[]).map(i=>`
    <div class="weak-item ${sevClass(i.severity)}">
      <div class="lag-top">
        <strong>${esc(i.weakness)}</strong>
        <span class="sev">${esc(i.severity)}</span>
      </div>
      <p><b>Root cause:</b> ${esc(i.root_cause)}</p>
      <p>${esc(i.evidence)}</p>
      <small>Related: ${esc(i.related_area)}</small>
    </div>`).join("");
}

function renderStudy(sp){
  if(!sp)return;
  setText("studyTitle",`${sp.duration} real-world plan`);
  setText("studyHours",`${sp.weekly_hours} hrs / week`);
  setText("studyOverview",sp.overview);
  setText("studyDuration",sp.duration);
  $("#studyHabits").innerHTML=(sp.daily_habits||[]).map(h=>`<li>${esc(h)}</li>`).join("");
  $("#studyTools").innerHTML=(sp.tools_and_platforms||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join("");
  $("#studyPhases").innerHTML=(sp.phases||[]).map((p,i)=>`
    <article class="study-phase">
      <div class="phase-num">${i+1}</div>
      <div>
        <div class="phase-head">
          <strong>${esc(p.phase)}</strong>
          <span>${esc(p.focus_skill)}</span>
        </div>
        <p class="narrative">${esc(p.daily_routine)}</p>
        <div class="phase-cols">
          <div>
            <span class="section-kicker">Practice</span>
            <ul class="clean-list">${(p.practice_tasks||[]).map(t=>`<li>${esc(t)}</li>`).join("")}</ul>
          </div>
          <div>
            <span class="section-kicker">Resources</span>
            <ul class="clean-list">${(p.real_world_resources||[]).map(t=>`<li>${esc(t)}</li>`).join("")}</ul>
          </div>
        </div>
        <div class="checkpoint"><b>Checkpoint:</b> ${esc(p.success_checkpoint)}</div>
      </div>
    </article>`).join("");
}

function renderAudit(r){
  setText("auditId", r.report_id || "—");
  setText("auditTime", r.generated_at ? new Date(r.generated_at).toLocaleString() : "—");
}

function renderGates(r){
  const a=r.academic_snapshot, att=r.attendance_snapshot, iv=r.interview_deep_dive, o=r.overall_performance;
  const gates=[
    {id:"cgpa", label:"CGPA ≥ 7.0 shortlist filter", pass:a.cgpa>=7.0, detail:`CGPA ${a.cgpa.toFixed(2)}/10`},
    {id:"att", label:"Attendance Eligible (≥ 75%)", pass:att.status==="Eligible", detail:`${att.percentage.toFixed(1)}% · ${att.status}`},
    {id:"iv", label:"Interview panel ≥ 7.0 / 10", pass:iv.overall_score>=7.0, detail:`${iv.overall_score.toFixed(1)}/10`},
    {id:"ontime", label:"On-time submissions ≥ 90%", pass:a.on_time_rate>=90, detail:`${a.on_time_rate.toFixed(0)}% on-time`},
    {id:"comp", label:"Composite ≥ 70 for mass drives", pass:o.score>=70, detail:`Composite ${o.score.toFixed(1)}`},
    {id:"tier", label:"Tier 1 or Tier 2 cohort", pass:(r.performance_tier?.tier||3)<=2, detail:r.performance_tier?.label || "—"}
  ];
  const passed=gates.filter(g=>g.pass).length;
  setText("gatesSummary", `${passed}/${gates.length} gates cleared`);
  $("#gateList").innerHTML=gates.map(g=>`
    <div class="gate ${g.pass?"pass":"fail"}">
      <span class="gate-mark">${g.pass?"PASS":"FAIL"}</span>
      <div>
        <strong>${esc(g.label)}</strong>
        <small>${esc(g.detail)}</small>
      </div>
    </div>`).join("");
}

function traitScore(rating){
  const key=String(rating||"").trim().toLowerCase();
  return TRAIT_MAP[key] ?? 5;
}

function drawTraitChart(observations){
  const obs=observations||[];
  if(!obs.length){ destroyChart("traitChart"); return; }
  makeChart("traitChart", {
    type:"radar",
    data:{
      labels: obs.map(o=>o.trait),
      datasets:[{
        label:"Panel rating / 10",
        data: obs.map(o=>traitScore(o.rating)),
        backgroundColor:"rgba(31,92,77,0.18)",
        borderColor:ACCENT,
        pointBackgroundColor:ACCENT,
        borderWidth:2
      }]
    },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false}},
      scales:{r:{min:0, max:10, ticks:{stepSize:2, backdropColor:"transparent"}, grid:{color:TRACK}, angleLines:{color:TRACK}, pointLabels:{font:{size:11}, color:INK}}}
    }
  });
  $("#traitList").innerHTML=obs.map(o=>`
    <div class="trait-row">
      <span>${esc(o.trait)}</span>
      <b>${esc(o.rating)}</b>
      <div class="trait-bar"><i style="width:${traitScore(o.rating)*10}%"></i></div>
    </div>`).join("");
}

function renderTranscript(r){
  const el=$("#transcript"); if(!el)return;
  const srcQs = sources?.["interview.json"]?.questions || sources?.interview?.questions || [];
  const insights = r.interview_deep_dive?.questions || [];
  const rows = insights.map((q,i)=>{
    const src = srcQs[i] || srcQs.find(s=>s.question===q.question) || {};
    return `
      <article class="transcript-item">
        <div class="t-q"><span>Q${i+1}</span> ${esc(q.question)}</div>
        <div class="t-a"><em>Student</em><p>${esc(src.student_answer || "Answer not in loaded source bundle.")}</p></div>
        <div class="t-f"><em>Panel</em><p>${esc(src.feedback || "—")}</p></div>
        <div class="t-score">${q.score}/10 · ${esc(q.verdict)} · ${esc(q.topic)}</div>
      </article>`;
  }).join("");
  el.innerHTML = rows || "<p class='muted'>No transcript questions available.</p>";
}

function predictTier(score, eligible, interview){
  if(eligible && score>=85 && interview>=8) return {tier:1, label:"Tier 1", title:"Placement Ready Elite"};
  if(eligible && score>=70) return {tier:2, label:"Tier 2", title:"Competitive Contender"};
  return {tier:3, label:"Tier 3", title:"Foundation Builder"};
}
function predictStatus(score, eligible){
  if(!eligible) return score>=55 ? "Needs Preparation" : "Not Ready";
  if(score>=85) return "Placement Ready";
  if(score>=70) return "Almost Ready";
  if(score>=55) return "Needs Preparation";
  return "Not Ready";
}

/** Same readiness formula as backend WhatIfScenario */
function readinessFromLevers(iv, asg, att, dsa, comms){
  let score = iv*10*0.30 + asg*0.25 + att*0.10 + dsa*10*0.20 + comms*10*0.15;
  if(att < 75) score = Math.min(score, 45);
  return +Math.max(0, Math.min(100, score)).toFixed(2);
}

function leverFromReport(r, key, fallback){
  const lev = (r.what_if_scenario?.levers||[]).find(l=>l.key===key);
  return lev ? Number(lev.current) : fallback;
}

function syncSimulatorFromReport(r){
  if(!r) return;
  const a=r.academic_snapshot, att=r.attendance_snapshot, iv=r.interview_deep_dive;
  $("#simInterview").value = leverFromReport(r, "interview", iv.overall_score);
  $("#simAssign").value = leverFromReport(r, "assignments", a.assignment_average);
  $("#simAttend").value = leverFromReport(r, "attendance", att.percentage);
  $("#simDsa").value = leverFromReport(r, "dsa", 5);
  $("#simComms").value = leverFromReport(r, "communication", 5);
  updateSimulator();
}

function applyRecommendedLevers(){
  if(!report?.what_if_scenario?.levers) return;
  for(const lev of report.what_if_scenario.levers){
    const map = {
      attendance: "simAttend",
      interview: "simInterview",
      assignments: "simAssign",
      dsa: "simDsa",
      communication: "simComms"
    };
    const id = map[lev.key];
    if(id && $("#"+id)) $("#"+id).value = lev.recommended;
  }
  updateSimulator();
}

function updateSimulator(){
  if(!report) return;
  const iv = Number($("#simInterview").value);
  const asg = Number($("#simAssign").value);
  const att = Number($("#simAttend").value);
  const dsa = Number($("#simDsa").value);
  const comms = Number($("#simComms").value);
  setText("simIvOut", iv.toFixed(1));
  setText("simAsgOut", asg.toFixed(0)+"%");
  setText("simAttOut", att.toFixed(1)+"%");
  setText("simDsaOut", dsa.toFixed(1));
  setText("simComOut", comms.toFixed(1));

  const base = report.what_if_scenario;
  const currentReady = base
    ? Number(base.current_readiness)
    : readinessFromLevers(
        leverFromReport(report,"interview", report.interview_deep_dive.overall_score),
        leverFromReport(report,"assignments", report.academic_snapshot.assignment_average),
        leverFromReport(report,"attendance", report.attendance_snapshot.percentage),
        leverFromReport(report,"dsa", 5),
        leverFromReport(report,"communication", 5)
      );
  const simulated = readinessFromLevers(iv, asg, att, dsa, comms);
  const eligible = att >= 75;
  const status = predictStatus(simulated, eligible);
  const delta = +(simulated - currentReady).toFixed(2);

  // Largest improvement drivers vs current report levers
  const cur = {
    Interview: leverFromReport(report,"interview", report.interview_deep_dive.overall_score),
    Assignments: leverFromReport(report,"assignments", report.academic_snapshot.assignment_average),
    Attendance: leverFromReport(report,"attendance", report.attendance_snapshot.percentage),
    DSA: leverFromReport(report,"dsa", 5),
    Communication: leverFromReport(report,"communication", 5)
  };
  const now = { Interview: iv, Assignments: asg, Attendance: att, DSA: dsa, Communication: comms };
  const weights = { Interview: 3.0, Assignments: 0.25, Attendance: 0.10, DSA: 2.0, Communication: 1.5 };
  const contrib = Object.keys(now)
    .map(k=>({k, lift:(now[k]-cur[k])*weights[k]}))
    .filter(x=>x.lift>0.05)
    .sort((a,b)=>b.lift-a.lift);
  const drivers = contrib.slice(0,2).map(x=>x.k);
  const driverLabel = drivers.length ? drivers.join(" + ") : (delta<=0 ? "No lift yet" : "Balanced gains");

  setText("simCurrentReady", currentReady.toFixed(0)+"%");
  setText("simComposite", simulated.toFixed(0)+"%");
  setText("simStatus", status);
  setText("simEligible", eligible ? "Yes (≥75%)" : "No — blocked");
  setText("simDelta", `${delta>=0?"+":""}${delta.toFixed(1)} pts`);
  setText("simDriver", driverLabel);
  setText("simNote",
    eligible
      ? `Current readiness ${currentReady.toFixed(0)}% → simulated ${simulated.toFixed(0)}%. Largest improvement driver: ${driverLabel}. ${delta>0?"This turns the dashboard into a counseling tool.":delta<0?"Regression from current — avoid.":"Matches the current baseline."}`
      : `Attendance below 75% caps readiness at 45% regardless of interview or DSA gains. Clear attendance first.`
  );
}

function renderEarlyWarning(ew){
  if(!ew || !$("#earlyWarning")) return;
  const sev = ew.severity || "clear";
  setText("ewSeverity", sev.toUpperCase());
  setText("ewTitle", ew.title || "—");
  setText("ewTrajectory", ew.trajectory_summary || "");
  setText("ewIssue", ew.predicted_issue || "—");
  setText("ewIntervention", ew.recommended_intervention || "—");
  const banner = $("#ewBanner");
  if(banner) banner.dataset.severity = sev;
  $("#ewSignals").innerHTML = (ew.signals||[]).length
    ? ew.signals.map(s=>`
      <div class="ew-signal dir-${esc(s.direction)}">
        <span class="ew-metric">⚠ ${esc(s.metric)}</span>
        <strong>${esc(s.delta_label)}</strong>
        <p>${esc(s.detail)}</p>
      </div>`).join("")
    : `<div class="ew-signal dir-flat"><span class="ew-metric">All clear</span><strong>No downward trajectory signals</strong><p>Healthy bands hold — keep monitoring.</p></div>`;
}

function buildSkillTreeAscii(sg){
  if(!sg?.nodes?.length) return "";
  const byId = Object.fromEntries(sg.nodes.map(n=>[n.id,n]));
  const cell = (id, w=18) => {
    const n = byId[id];
    if(!n) return "".padEnd(w);
    const t = `${n.label} ${Math.round(n.score)}%`;
    return t.length > w ? t.slice(0,w-1)+"…" : t.padEnd(w);
  };
  const root = byId.core_lang || sg.nodes.find(n=>n.layer==="foundation") || sg.nodes[0];
  return [
    `              ${root.label} (${Math.round(root.score)}%)`,
    `                 │`,
    `     ┌───────────┼───────────┐`,
    `     ↓           ↓           ↓`,
    ` ${cell("oop")} ${cell("dsa")} ${cell("sql")}`,
    `     │           │           │`,
    `     └─────┐     │     ┌─────┘`,
    `           ↓     ↓     ↓`,
    `        ${cell("backend",20)} ${cell("problem_solving",20)}`,
    `              \\   |   /`,
    `         ${cell("comms",16)} + ${cell("delivery",20)}`,
    `                   ↓`,
    `            ${cell("placement",22)}`,
    ``,
    `Bottleneck: ${sg.bottleneck_skill} → ${sg.downstream_count} downstream`
  ].join("\n");
}

function buildSkillMapSvg(sg){
  if(!sg?.nodes?.length) return "";
  const layers = {
    foundation: sg.nodes.filter(n=>n.layer==="foundation"),
    core: sg.nodes.filter(n=>n.layer==="core"),
    applied: sg.nodes.filter(n=>n.layer==="applied"),
    outcome: sg.nodes.filter(n=>n.layer==="outcome")
  };
  const order = ["foundation","core","applied","outcome"];
  const W = 920, H = 340, colW = W / 4;
  const pos = {};
  order.forEach((layer, li) => {
    const nodes = layers[layer] || [];
    const gap = H / (nodes.length + 1);
    nodes.forEach((n, i) => {
      pos[n.id] = { x: colW * li + colW/2, y: gap * (i + 1), n };
    });
  });
  const bottle = (sg.nodes.find(n=>n.label===sg.bottleneck_skill)||{}).id;
  const edgeLines = (sg.edges||[]).map(e=>{
    const a = pos[e.source], b = pos[e.target];
    if(!a||!b) return "";
    const midX = (a.x + b.x) / 2;
    const fragile = e.strength === "fragile";
    const cls = fragile ? "sg-edge fragile" : (e.strength === "adequate" ? "sg-edge adequate" : "sg-edge");
    return `<path class="${cls}" d="M${a.x+54},${a.y} C${midX},${a.y} ${midX},${b.y} ${b.x-54},${b.y}" fill="none"/>`;
  }).join("");
  const nodeRects = Object.values(pos).map(({x,y,n})=>{
    const isBottle = n.id === bottle;
    const health = n.health || (n.score < 55 ? "blocking" : n.score < 70 ? "watch" : "healthy");
    return `
      <g class="sg-node-g health-${esc(health)}${isBottle?" bottle":""}" transform="translate(${x},${y})">
        <rect x="-54" y="-28" width="108" height="56" rx="2"/>
        <text class="sg-lab" y="-6" text-anchor="middle">${esc(n.label)}</text>
        <text class="sg-pct" y="14" text-anchor="middle">${Math.round(n.score)}%</text>
      </g>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="sg-svg" role="presentation">
    <defs>
      <marker id="sgArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 z" fill="#5c1a4a"/>
      </marker>
    </defs>
    <text x="${colW/2}" y="18" class="sg-col" text-anchor="middle">Foundation</text>
    <text x="${colW*1.5}" y="18" class="sg-col" text-anchor="middle">Core</text>
    <text x="${colW*2.5}" y="18" class="sg-col" text-anchor="middle">Applied</text>
    <text x="${colW*3.5}" y="18" class="sg-col" text-anchor="middle">Outcome</text>
    ${edgeLines}
    ${nodeRects}
  </svg>`;
}

function renderSkillGraph(sg){
  if(!sg || !$("#skillGraph")) return;
  setText("sgRoot", `Root · ${sg.root_skill||"—"}`);
  setText("sgInsight", sg.insight || "");
  setText("sgBottleneck", `Bottleneck: ${sg.bottleneck_skill} · ${sg.downstream_count} downstream area(s)`);
  const map = $("#sgMap");
  if(map) map.innerHTML = buildSkillMapSvg(sg);
  const tree = $("#sgTree");
  if(tree) tree.textContent = buildSkillTreeAscii(sg);
  $("#sgNodes").innerHTML = (sg.nodes||[]).map(n=>{
    const health = n.health || "healthy";
    return `<div class="sg-node layer-${esc(n.layer)} health-${esc(health)}">
      <strong>${esc(n.label)}</strong>
      <b>${Math.round(n.score)}%</b>
      <span>${esc(n.band)} · ${esc(n.layer)} · ${esc(health)}</span>
      <em>${esc(n.evidence||"")}</em>
      <div class="sg-bar"><i style="width:${n.score}%"></i></div>
    </div>`;
  }).join("");
}

function setPipelineStages(state){
  // state: idle | running | done | error
  const items = $$("#pipelineStages li");
  items.forEach((li,i)=>{
    li.classList.remove("active","done","error");
    if(state==="idle") return;
    if(state==="error"){ li.classList.add("error"); return; }
    if(state==="done"){ li.classList.add("done"); return; }
    if(state==="running"){
      if(i < (setPipelineStages._step||0)) li.classList.add("done");
      else if(i === (setPipelineStages._step||0)) li.classList.add("active");
    }
  });
}
function animatePipeline(ms=900){
  return new Promise(resolve=>{
    setPipelineStages._step = 0;
    setPipelineStages("running");
    const tick = ()=>{
      setPipelineStages._step += 1;
      if(setPipelineStages._step >= 4){ setPipelineStages("done"); resolve(); return; }
      setPipelineStages("running");
      setTimeout(tick, ms/4);
    };
    setTimeout(tick, ms/4);
  });
}

function setActiveProfile(profile){
  $$(".profile-btn").forEach(b=>b.classList.toggle("active", b.dataset.profile===profile));
}


function drawReferenceTemplateCharts(r){
  if(typeof Chart==="undefined") return;
  const dims=(r.dimension_scores||[]).slice();
  destroyChart("templateTrendChart");
  destroyChart("templateSkillChart");

  const labels=dims.map(d=>d.name);
  const scores=dims.map(d=>Number(d.score||0));
  const avg=labels.map(()=>DEPT_AVG);

  makeChart("templateTrendChart",{
    type:"line",
    data:{labels,datasets:[
      {label:"Student",data:scores,borderColor:"#3188e8",backgroundColor:"rgba(49,136,232,.08)",pointBackgroundColor:"#3188e8",pointRadius:4,borderWidth:2,tension:.35,fill:false},
      {label:"Average",data:avg,borderColor:"#0b9b72",pointBackgroundColor:"#0b9b72",pointRadius:3,borderWidth:2,tension:.35,fill:false}
    ]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"bottom",labels:{boxWidth:10,font:{size:10}}}},
      scales:{y:{min:0,max:100,grid:{color:"#e7edf3"},ticks:{font:{size:9}}},x:{grid:{display:false},ticks:{font:{size:9},maxRotation:25,minRotation:0}}}}
  });

  makeChart("templateSkillChart",{
    type:"radar",
    data:{labels,datasets:[
      {label:"Your Score",data:scores,backgroundColor:"rgba(24,170,139,.18)",borderColor:"#14a982",pointBackgroundColor:"#14a982",pointBorderColor:"#fff",borderWidth:2,pointRadius:3},
      {label:"Average",data:avg,backgroundColor:"rgba(100,117,139,.03)",borderColor:"#68798e",borderDash:[5,5],pointRadius:0,borderWidth:1.5}
    ]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"top",labels:{boxWidth:12,font:{size:9}}}},
      scales:{r:{min:0,max:100,ticks:{stepSize:20,backdropColor:"transparent",font:{size:8}},grid:{color:"#dbe4ed"},angleLines:{color:"#dbe4ed"},pointLabels:{color:"#314b68",font:{size:10}}}}}
  });
}

function populateReferenceTemplate(r){
  if(!r) return;
  const a=r.academic_snapshot||{}, iv=r.interview_deep_dive||{}, pr=r.placement_readiness||{};
  const overall=r.overall_performance||{};
  const assignment=Number(a.assignment_average||0);
  const assessment=Number(a.assessment_average||0);
  const interview=Number(iv.overall_score||0);
  const readiness=Number(pr.confidence||overall.score||0);

  setText("kpiOverall",pct(overall.score));
  setText("kpiAssignment",pct(assignment));
  setText("kpiAssessment",pct(assessment));
  setText("kpiMock",interview.toFixed(1)+"/10");
  setText("kpiResume",Math.round(readiness)+"%");
  setText("kpiOverallDelta",overall.status||"Current report");
  setText("kpiResumeSub",pr.status||"Readiness confidence");

  setText("profileName",r.student_name||"Student");
  setText("profileId","ID: "+(r.student_id||"—"));
  setText("semesterValue",sources?.["student.json"]?.semester ? `CRT ${sources["student.json"].semester}` : "Current semester");
  setText("dateValue",r.generated_at ? new Date(r.generated_at).toLocaleDateString(undefined,{weekday:"long",month:"short",day:"numeric",year:"numeric"}) : new Date().toLocaleDateString());

  const dims=r.dimension_scores||[];
  const findDim=(...terms)=>{
    const d=dims.find(x=>terms.some(t=>String(x.name||"").toLowerCase().includes(t)));
    return d ? `${Math.round(d.score)}%` : "—";
  };
  setText("readyDsa",findDim("dsa","data structure"));
  setText("readyDev",findDim("development","coding","programming"));
  setText("readyApt",findDim("aptitude","quantitative"));
  setText("readyComm",findDim("communication","soft skill"));

  const ring=$("#templateReadinessRing");
  if(ring){
    const circumference=2*Math.PI*60;
    ring.style.strokeDasharray=String(circumference);
    ring.style.strokeDashoffset=String(circumference*(1-Math.min(100,Math.max(0,readiness))/100));
  }
  setText("templateReadiness",Math.round(readiness)+"%");

  const strengths=(r.strengths||[]).slice(0,4);
  const improvements=(r.growth_areas||[]).slice(0,4);
  const gaps=(r.lagging_areas||[]).slice(0,4);
  const makeItems=(items, kind)=>items.length ? items.map(x=>{
    const title=x.title||x.area||"Focus area";
    const text=x.evidence||x.fix_hint||x.narrative||"See detailed report.";
    return `<div class="list-item-template"><span class="list-dot">${kind==="good"?"✓":"!"}</span><span><strong>${esc(title)}</strong><br>${esc(text)}</span></div>`;
  }).join("") : `<div class="list-item-template"><span class="list-dot">•</span><span>No items recorded in the current report.</span></div>`;
  const se=$("#templateStrengths"); if(se) se.innerHTML=makeItems(strengths,"good");
  const ie=$("#templateImprovements"); if(ie) ie.innerHTML=makeItems(improvements,"bad");
  const ge=$("#templateGaps"); if(ge) ge.innerHTML=makeItems(gaps,"bad");

  const q=$("#templateQuote"); if(q) q.textContent="A little progress each day adds up to big results.";
  drawReferenceTemplateCharts(r);
}

function render(r){
  report=r;
  populateReferenceTemplate(r);
  const o=r.overall_performance, a=r.academic_snapshot, att=r.attendance_snapshot, iv=r.interview_deep_dive, pr=r.placement_readiness;
  setText("studentName",r.student_name); setText("headline",r.headline);
  $("#studentMeta").innerHTML=[r.student_id,`${a.cgpa.toFixed(1)} CGPA`,iv.role,iv.company,`${r.meta.engine} engine`].filter(Boolean).map(x=>`<span>${esc(x)}</span>`).join("");
  setText("overallScore",Math.round(o.score));setText("grade",`${o.letter} · ${o.status}`);
  $("#scoreRing").style.strokeDashoffset=414-(414*Math.min(100,o.score)/100);
  $("#statusPill").textContent=o.status;

  renderTier(r.performance_tier);
  renderAudit(r);
  renderGates(r);

  setText("kpiAcademic",pct((a.assignment_average+a.assessment_average)/2));
  setText("kpiInterview",iv.overall_score.toFixed(1)+"/10");
  setText("kpiAttendance",pct(att.percentage));
  setText("kpiReadiness",pr.confidence.toFixed(0)+"%");
  $("#barAcademic").style.width=((a.assignment_average+a.assessment_average)/2)+"%";
  $("#barInterview").style.width=(iv.overall_score*10)+"%";
  $("#barAttendance").style.width=att.percentage+"%";
  $("#barReadiness").style.width=pr.confidence+"%";

  $("#dimensions").innerHTML=r.dimension_scores.map(d=>{
    const vs = d.score - DEPT_AVG;
    return `<div class="dim-row"><span class="name">${esc(d.name)}</span><div class="dim-track"><i style="width:${d.score}%"></i></div><b class="dim-score">${Math.round(d.score)}</b><span class="dim-band">${esc(d.band)} · vs dept ${vs>=0?"+":""}${vs.toFixed(0)} — ${esc(d.narrative)}</span></div>`;
  }).join("");
  $("#summary").innerHTML=r.executive_summary.split(/\n{2,}/).map(p=>`<p>${esc(p)}</p>`).join("") || `<p>${esc(r.executive_summary)}</p>`;

  drawCharts(r);
  drawTraitChart(iv.observations);
  renderLagging(r.lagging_areas);
  renderWeakness(r.weakness_analysis);
  $("#riskFlags").innerHTML=(r.risk_flags||[]).length
    ? r.risk_flags.map(x=>`<li>${esc(x)}</li>`).join("")
    : "<li>No risk flags recorded.</li>";
  renderEarlyWarning(r.early_warning);
  renderSkillGraph(r.skill_graph);

  setText("cgpa",`CGPA ${a.cgpa.toFixed(1)}`);setText("academicNarrative",a.narrative);
  $("#academicItems").innerHTML=a.items.map(i=>`<div class="table-row"><div>${esc(i.title)}<small>${esc(i.subject)} • ${esc(i.id)}</small></div><strong>${i.percent.toFixed(1)}%</strong><span></span></div>`).join("");
  setText("attendanceStatus",att.status);setText("attendanceBig",att.percentage.toFixed(1)+"%");
  $(".donut").style.setProperty("--p",att.percentage+"%");
  $("#attendanceFacts").innerHTML=`<div><b>${att.present_days}</b> present days</div><div><b>${att.working_days-att.present_days}</b> absent / leave</div><div><b>${att.working_days}</b> working days</div>`;
  setText("attendanceNarrative",att.narrative);
  setText("interviewContext",`${iv.company} • ${iv.role} • ${iv.interview_date}`);
  setText("interviewBig",iv.overall_score.toFixed(1));
  setText("strongTopic",iv.strongest_topic);setText("weakTopic",iv.weakest_topic);
  setText("interviewNarrative",iv.narrative);
  renderTranscript(r);
  $("#questions").innerHTML=iv.questions.map((q,i)=>`<div class="question"><div class="q">${i+1}. ${esc(q.question)}</div><div class="answer">${esc(q.coaching_note)}</div><div class="score">${q.score}/10 • ${esc(q.verdict)} • ${esc(q.topic)}</div></div>`).join("");

  setText("confidence",pr.confidence.toFixed(0)+"% confidence");
  setText("readinessStatus",pr.status);setText("readinessNarrative",pr.narrative);
  $("#roles").innerHTML=pr.target_roles.map(x=>`<span class="tag">${esc(x)}</span>`).join("");
  $("#companies").innerHTML=pr.company_fit.map(x=>`<span class="tag">${esc(x)}</span>`).join("");
  $("#blockers").innerHTML=pr.blockers.length?pr.blockers.map(x=>`<li>${esc(x)}</li>`).join(""):"<li>No major blockers recorded.</li>";
  $("#actionPlan").innerHTML=r.action_plan.map(x=>`<div class="action"><div class="num">${x.priority}</div><div class="time">${esc(x.timeframe)}</div><div><strong>${esc(x.skill)}</strong><small>${esc(x.action)}<br><b>Success:</b> ${esc(x.success_metric)}</small></div></div>`).join("");

  renderStudy(r.study_plan);
  renderOutbox(r);
  renderFinalReport(r);
  syncSimulatorFromReport(r);

  $("#strengths").innerHTML=r.strengths.map(x=>`<div class="evidence"><strong>${esc(x.title)}</strong><p>${esc(x.evidence)}</p><em>${esc(x.why_it_matters)}</em></div>`).join("");
  $("#growth").innerHTML=r.growth_areas.map(x=>`<div class="evidence growth"><strong>${esc(x.title)}</strong><p>${esc(x.evidence)}</p><em>${esc(x.why_it_matters)}</em></div>`).join("");
  setText("recommendation",r.counselor_recommendation);setText("closing",r.closing_note);
  $("#rawJson").textContent=JSON.stringify(r,null,2);
  if (window.MeridianWorld && typeof window.MeridianWorld.pulse === "function") {
    window.MeridianWorld.pulse(r.performance_tier?.tier || 2);
  }
}

function fillSources(bundle){
  // Normalize both {"student.json":...} and {"student":...} shapes
  const normalized={};
  for(const [k,id] of Object.entries(sourceIds)){
    const val = bundle[`${k}.json`] ?? bundle[k];
    normalized[`${k}.json`] = val;
    if(val!=null) $("#"+id).value=JSON.stringify(val,null,2);
  }
  sources=normalized;
}

async function getDemo(profile="strong"){
  setActiveProfile(profile==="at-risk"?"at-risk":"strong");
  setRun("Running terminal pipeline…");
  animatePipeline(1200);
  try{
    const q = profile==="at-risk" ? "?profile=at-risk" : "";
    const x=await fetch("/api/demo"+q);
    const d=await x.json();
    if(!x.ok)throw new Error(d.detail||d.error||d.stderr||"Demo failed");
    const bundleUrl = profile==="at-risk" ? "/mock-bundle-at-risk.json" : "/mock-bundle.json";
    try{ const b=await (await fetch(bundleUrl)).json(); fillSources(b); }catch(_){}
    render(d.report);
    const ms = d.pipeline?.timing_ms ? ` · ${d.pipeline.timing_ms}ms` : "";
    setPipelineStages("done");
    setRun(`Pipeline completed • ${d.pipeline?.profile||profile} • ${(d.report.meta?.engine||"local")} engine${ms}`,true);
  }catch(e){
    setPipelineStages("error");
    setRun("Pipeline error: "+e.message,false,true);
  }
}

async function loadMockSources(){
  try{
    const r=await fetch("/mock-bundle.json"); const b=await r.json(); fillSources(b);
  }catch(e){ setRun("Could not load mock input bundle: "+e.message,false,true); }
}
function setRun(msg,ok=false,err=false){$("#runStatus").textContent=msg;$("#runStatus").className=err?"run-error":ok?"success":"";}

async function runCustom(){
  try{
    const bundle={};for(const [k,id] of Object.entries(sourceIds))bundle[`${k}.json`]=JSON.parse($("#"+id).value);
    setRun("Executing unchanged Python pipeline on temporary source set…");
    animatePipeline(1400);
    const x=await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sources:bundle})});
    const d=await x.json();if(!x.ok)throw new Error(d.detail||d.error||d.stderr||"Run failed");
    fillSources(bundle);
    render(d.report);
    setPipelineStages("done");
    const ms = d.pipeline?.timing_ms ? ` · ${d.pipeline.timing_ms}ms` : "";
    setRun(`New student processed • Load → Validate → KPI → Report${ms}`,true);
    document.getElementById("overview").scrollIntoView({behavior:"smooth"});
  }catch(e){ setPipelineStages("error"); setRun("Input / pipeline error: "+e.message,false,true); }
}

function exportReport(){
  if(!report) return;
  const a=document.createElement("a");
  a.href=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:"application/json"}));
  a.download=`${report.report_id||"student-report"}.json`;
  a.click();
}

function renderFinalReport(r){
  if(!r || !$("#finalReport")) return;
  const o=r.overall_performance, bd=r.board_decision||{}, sc=r.scorecard||[];
  const iv=r.interview_deep_dive, pr=r.placement_readiness;

  setText("frStudent", r.student_name);
  setText("frHeadline", r.headline);
  $("#frCoverMeta").innerHTML=[
    `ID ${esc(r.student_id)}`,
    `Report ${esc(r.report_id)}`,
    r.generated_at ? new Date(r.generated_at).toLocaleString() : "",
    `${esc(o.letter)} · ${esc(o.status)} · ${esc(r.performance_tier?.label)}`,
    `${esc(iv.company)} · ${esc(iv.role)}`
  ].filter(Boolean).map(x=>`<span>${x}</span>`).join("");

  const code=bd.decision||"PENDING";
  const box=$("#frDecision");
  if(box){
    box.dataset.decision=code;
    box.className=`fr-decision dec-${code}`;
  }
  setText("frDecisionCode", code.replace(/_/g," "));
  setText("frDecisionLabel", bd.decision_label||o.status);
  setText("frDecisionWhy", bd.rationale||r.counselor_recommendation);
  setText("frPriority", bd.priority_fix||r.weakness_analysis?.primary_weakness||"—");
  setText("frReview", bd.next_review_date||"—");
  setText("frSigned", bd.signed_by||r.meta?.engine||"—");

  const tb=$("#frScorecard tbody");
  if(tb){
    tb.innerHTML=sc.map(row=>`
      <tr class="res-${esc(row.result).toLowerCase()}">
        <td>${esc(row.metric)}</td>
        <td>${esc(row.value)}</td>
        <td>${esc(row.benchmark)}</td>
        <td><b>${esc(row.result)}</b></td>
      </tr>`).join("") || `<tr><td colspan="4">Scorecard not in report.</td></tr>`;
  }

  $("#frExec").innerHTML=(r.executive_summary||"").split(/\n{2,}/).map(p=>`<p>${esc(p)}</p>`).join("");
  $("#frDims").innerHTML=(r.dimension_scores||[]).map(d=>`
    <div class="fr-dim">
      <div class="fr-dim-top"><strong>${esc(d.name)}</strong><span>${Math.round(d.score)} · ${esc(d.band)}</span></div>
      <div class="fr-dim-bar"><i style="width:${d.score}%"></i></div>
      <p>${esc(d.narrative)}</p>
    </div>`).join("");

  setText("frWeakSummary", r.weakness_analysis?.summary||"");
  $("#frWeakList").innerHTML=(r.weakness_analysis?.items||[]).map(i=>
    `<li><b>${esc(i.weakness)}</b> (${esc(i.severity)}) — ${esc(i.root_cause)}</li>`
  ).join("");
  $("#frLagList").innerHTML=(r.lagging_areas||[]).map(a=>
    `<li><b>${esc(a.area)}</b>: ${Math.round(a.current_score)} → ${Math.round(a.target_score)} (gap ${Math.round(a.gap)}) — ${esc(a.fix_hint)}</li>`
  ).join("");

  const ew=r.early_warning||{};
  setText("frEwTitle", ew.title||"No early warning");
  setText("frEwSummary", ew.trajectory_summary||"");
  setText("frEwIssue", ew.predicted_issue||"—");
  setText("frEwIntervention", ew.recommended_intervention||"—");
  const frEw=$("#frEwBox");
  if(frEw) frEw.dataset.severity = ew.severity||"clear";
  $("#frEwSignals").innerHTML=(ew.signals||[]).map(s=>
    `<li><b>${esc(s.metric)}</b> ${esc(s.delta_label)} — ${esc(s.detail)}</li>`
  ).join("") || "<li>No downward signals.</li>";

  const sg=r.skill_graph||{};
  setText("frSgInsight", sg.insight||"");
  const frTree=$("#frSgTree");
  if(frTree) frTree.textContent = buildSkillTreeAscii(sg);
  $("#frSgNodes").innerHTML=(sg.nodes||[]).map(n=>
    `<li><b>${esc(n.label)}</b>: ${Math.round(n.score)}% (${esc(n.band)} · ${esc(n.health||"")}) — ${esc(n.evidence||n.layer)}</li>`
  ).join("");
  setText("frSgBottleneck", sg.bottleneck_skill
    ? `Bottleneck skill: ${sg.bottleneck_skill} — improving it lifts ${sg.downstream_count} downstream area(s).`
    : "");

  const wi=r.what_if_scenario||{};
  setText("frSimCurrent", wi.current_readiness!=null ? `${Math.round(wi.current_readiness)}%` : "—");
  setText("frSimSim", wi.simulated_readiness!=null ? `${Math.round(wi.simulated_readiness)}%` : "—");
  setText("frSimDrivers", (wi.largest_drivers||[]).join(" + ") || "—");
  setText("frSimNarrative", wi.narrative||"");
  setText("frSimFormula", wi.formula_note||"");
  const frLev=$("#frSimLevers tbody");
  if(frLev){
    frLev.innerHTML=(wi.levers||[]).map(l=>{
      const cur = l.unit==="percent" ? `${l.current}%` : `${l.current}/10`;
      const rec = l.unit==="percent" ? `${l.recommended}%` : `${l.recommended}/10`;
      return `<tr><td>${esc(l.label)}</td><td>${esc(String(cur))}</td><td>${esc(String(rec))}</td></tr>`;
    }).join("") || `<tr><td colspan="3">No what-if levers in report.</td></tr>`;
  }

  setText("frPlace", pr.narrative);
  setText("frRoles", (pr.target_roles||[]).join(" · "));
  $("#frBlockers").innerHTML=(pr.blockers||[]).map(b=>`<li>${esc(b)}</li>`).join("")||"<li>None</li>";

  $("#frActions").innerHTML=(r.action_plan||[]).map(a=>
    `<li><b>${esc(a.timeframe)} · ${esc(a.skill)}</b> — ${esc(a.action)} <em>Success: ${esc(a.success_metric)}</em></li>`
  ).join("");
  setText("frStudyOverview", r.study_plan?.overview||"");
  $("#frPhases").innerHTML=(r.study_plan?.phases||[]).map(p=>`
    <div class="fr-phase">
      <strong>${esc(p.phase)}</strong> · ${esc(p.focus_skill)}
      <p>${esc(p.daily_routine)}</p>
      <small>Checkpoint: ${esc(p.success_checkpoint)}</small>
    </div>`).join("");

  setText("frCounsel", r.counselor_recommendation);
  setText("frClose", r.closing_note);
  setText("frMethod", r.methodology_note||"");
  setText("frFoot", `${r.report_id} · engine ${r.meta?.engine||"?"} · model ${r.meta?.model||"?"} · strict_json ${r.meta?.strict_json?"yes":"no"}`);
}

function buildMarkdown(r){
  if(!r) return "";
  const bd=r.board_decision||{};
  const lines=[
    `# Placement Report — ${r.student_name}`,
    ``,
    `**Report ID:** ${r.report_id}  `,
    `**Generated:** ${r.generated_at}  `,
    `**Student ID:** ${r.student_id}  `,
    `**Tier:** ${r.performance_tier?.label} — ${r.performance_tier?.title}  `,
    `**Overall:** ${r.overall_performance.score} (${r.overall_performance.letter}) · ${r.overall_performance.status}`,
    ``,
    `> ${r.headline}`,
    ``,
    `## Board decision`,
    ``,
    `**${bd.decision || "—"}** — ${bd.decision_label||""}`,
    ``,
    bd.rationale||"",
    ``,
    `- **Priority fix:** ${bd.priority_fix||""}`,
    `- **Next review:** ${bd.next_review_date||""}`,
    `- **Signed by:** ${bd.signed_by||""}`,
    ``,
    `## Scorecard`,
    ``,
    `| Metric | Value | Benchmark | Result |`,
    `| --- | --- | --- | --- |`,
    ...(r.scorecard||[]).map(row=>`| ${row.metric} | ${row.value} | ${row.benchmark} | ${row.result} |`),
    ``,
    `## Executive summary`,
    ``,
    r.executive_summary,
    ``,
    `## Dimension scores`,
    ``,
    ...(r.dimension_scores||[]).map(d=>`- **${d.name}** — ${d.score} (${d.band}): ${d.narrative}`),
    ``,
    `## Weakness analysis`,
    ``,
    r.weakness_analysis?.summary||"",
    ``,
    `Primary: ${r.weakness_analysis?.primary_weakness||""}`,
    ``,
    ...(r.weakness_analysis?.items||[]).map(i=>`- **${i.weakness}** (${i.severity}): ${i.root_cause} — ${i.evidence}`),
    ``,
    `## Lagging areas`,
    ``,
    ...(r.lagging_areas||[]).map(a=>`- **${a.area}**: ${a.current_score} → ${a.target_score} (gap ${a.gap}) — ${a.fix_hint}`),
    ``,
    `## Early warning system`,
    ``,
    `**${r.early_warning?.title||"Clear"}** (${r.early_warning?.severity||"clear"})`,
    ``,
    r.early_warning?.trajectory_summary||"",
    ``,
    ...(r.early_warning?.signals||[]).map(s=>`- **${s.metric}** ${s.delta_label} — ${s.detail}`),
    ``,
    `Predicted issue: ${r.early_warning?.predicted_issue||""}`,
    ``,
    `Recommended intervention: ${r.early_warning?.recommended_intervention||""}`,
    ``,
    `## Skill graph`,
    ``,
    r.skill_graph?.insight||"",
    ``,
    "```",
    buildSkillTreeAscii(r.skill_graph||{}),
    "```",
    ``,
    ...(r.skill_graph?.nodes||[]).map(n=>`- **${n.label}**: ${n.score}% (${n.band}) · ${n.layer}`),
    ``,
    `Bottleneck: ${r.skill_graph?.bottleneck_skill||""} → ${r.skill_graph?.downstream_count||0} downstream`,
    ``,
    `## What-if scenario`,
    ``,
    `Current readiness: ${r.what_if_scenario?.current_readiness??"—"}%  `,
    `Simulated readiness: ${r.what_if_scenario?.simulated_readiness??"—"}%  `,
    `Largest drivers: ${(r.what_if_scenario?.largest_drivers||[]).join(" + ")}`,
    ``,
    r.what_if_scenario?.narrative||"",
    ``,
    ...(r.what_if_scenario?.levers||[]).map(l=>`- **${l.label}**: ${l.current} → ${l.recommended} (${l.unit})`),
    ``,
    r.what_if_scenario?.formula_note||"",
    ``,
    `## Placement readiness`,
    ``,
    r.placement_readiness?.narrative||"",
    ``,
    `Roles: ${(r.placement_readiness?.target_roles||[]).join(", ")}`,
    ``,
    `Blockers:`,
    ...(r.placement_readiness?.blockers||[]).map(b=>`- ${b}`),
    ``,
    `## Action plan`,
    ``,
    ...(r.action_plan||[]).map(a=>`${a.priority}. **${a.timeframe} · ${a.skill}** — ${a.action} _(Success: ${a.success_metric})_`),
    ``,
    `## Study plan`,
    ``,
    r.study_plan?.overview||"",
    ``,
    ...(r.study_plan?.phases||[]).map(p=>`### ${p.phase} — ${p.focus_skill}\n${p.daily_routine}\nCheckpoint: ${p.success_checkpoint}`),
    ``,
    `## Counselor recommendation`,
    ``,
    r.counselor_recommendation,
    ``,
    r.closing_note,
    ``,
    `## Methodology`,
    ``,
    r.methodology_note||"",
    ``,
    `---`,
    `Engine: ${r.meta?.engine} · Model: ${r.meta?.model} · Strict JSON: ${r.meta?.strict_json}`
  ];
  return lines.join("\n");
}

function exportMarkdown(){
  if(!report) return;
  const a=document.createElement("a");
  a.href=URL.createObjectURL(new Blob([buildMarkdown(report)],{type:"text/markdown;charset=utf-8"}));
  a.download=`${report.report_id||"student-report"}.md`;
  a.click();
}

function printFinalReport(){
  document.body.classList.add("print-final");
  window.print();
  setTimeout(()=>document.body.classList.remove("print-final"), 500);
}

/* ── Out-of-the-box recruiter lab ───────────────────── */
const DRILL_BANK = {
  "SQL & Databases": [
    {q:"Explain the difference between INNER JOIN and LEFT JOIN with an example.", hint:"Draw two tables; show unmatched left rows."},
    {q:"When would you use a window function instead of GROUP BY?", hint:"Need row-level detail plus an aggregate."},
    {q:"How do you find the second-highest salary in a table?", hint:"DENSE_RANK or subquery with MAX."}
  ],
  "DSA & Problem Solving": [
    {q:"Reverse a linked list — walk through pointer changes aloud.", hint:"prev, curr, next — three pointers."},
    {q:"When is a hash map the wrong tool?", hint:"Ordered queries, memory-tight, adversarial keys."},
    {q:"Explain two-pointer vs sliding window with one problem each.", hint:"Palindrome / max sum subarray of size k."}
  ],
  "Web & APIs": [
    {q:"Design a REST endpoint to create a user. Status codes?", hint:"201 + Location; 400 validation; 409 conflict."},
    {q:"GET vs POST — idempotency and caching implications?", hint:"GET safe/idempotent; POST not."},
    {q:"What does FastAPI give you that Flask does not by default?", hint:"Type validation, OpenAPI docs, async."}
  ],
  "OOP & Design": [
    {q:"Name the four OOP pillars with a one-line real example each.", hint:"Encapsulate fields; inherit Vehicle; poly Shape.draw; abstract Payment."},
    {q:"Composition vs inheritance — when do you prefer composition?", hint:"Has-a relationships; avoid deep trees."}
  ],
  "Python Fundamentals": [
    {q:"List vs tuple — memory, mutability, and hashability.", hint:"Tuples hashable if elements are; lists never."},
    {q:"What does a decorator actually do under the hood?", hint:"Function that returns a wrapped function."}
  ],
  "Machine Learning": [
    {q:"Overfitting — how do you detect and reduce it?", hint:"Train/val gap; regularization, more data, simpler model."},
    {q:"Train / validation / test — why three splits?", hint:"Tune on val; final honest score on test once."}
  ],
  "Behavioural & Comms": [
    {q:"Tell me about a failure using STAR in under 90 seconds.", hint:"Situation → Task → Action → Result → learning."},
    {q:"Why should we hire you — three proof points only.", hint:"Skill + project metric + teamwork proof."}
  ],
  "Interview Performance": [
    {q:"Rebuild your weakest answer as Definition → Example → Trade-off.", hint:"60 seconds max."}
  ]
};
let drillTimer=null, drillLeft=60, drillTopicKey="";

function polarToCartesian(cx, cy, r, angleDeg){
  const a=(angleDeg-90)*Math.PI/180;
  return {x:cx+r*Math.cos(a), y:cy+r*Math.sin(a)};
}
function describeArc(cx,cy,r,startAngle,endAngle){
  const start=polarToCartesian(cx,cy,r,endAngle);
  const end=polarToCartesian(cx,cy,r,startAngle);
  const large=endAngle-startAngle<=180?0:1;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${large} 0 ${end.x} ${end.y}`;
}

function hireScoreFrom(r){
  const o=r.overall_performance.score;
  const iv=r.interview_deep_dive.overall_score;
  const eligible=r.attendance_snapshot.status==="Eligible";
  const cgpa=r.academic_snapshot.cgpa;
  let s = o*0.55 + iv*10*0.35 + Math.min(10,cgpa)*1.0;
  if(!eligible) s *= 0.55;
  if(r.risk_flags?.length>=3) s -= 6;
  return Math.max(0, Math.min(100, +s.toFixed(1)));
}

function setHireDial(score){
  const clamped=Math.max(0,Math.min(100,score));
  // polarToCartesian: 0°=top, 90°=right, 270°=left — upper arc runs 270 → 90
  const deg = 270 - (clamped/100)*180;
  const tip = polarToCartesian(100, 100, 72, deg);
  const needle = $("#dialNeedle");
  if(needle){ needle.setAttribute("x2", tip.x); needle.setAttribute("y2", tip.y); }
  const arc = $("#dialArc");
  if(arc){
    const end = Math.min(269.9, Math.max(90, deg));
    arc.setAttribute("d", describeArc(100,100,80, end, 270));
    arc.style.stroke = clamped>=75?ACCENT:clamped>=55?WARN:DANGER;
  }
}

function formatINR(n){
  if(n>=100000) return (n/100000).toFixed(1)+" L";
  return Math.round(n).toLocaleString("en-IN");
}

function renderOutbox(r){
  if(!r || !$("#outbox")) return;
  const o=r.overall_performance, a=r.academic_snapshot, iv=r.interview_deep_dive;
  const lag=r.lagging_areas?.[0];
  const weak=iv.weakest_topic;
  const strong=iv.strongest_topic;
  const eligible=r.attendance_snapshot.status==="Eligible";
  const hs=hireScoreFrom(r);

  // Focus spotlight — one thing
  setText("focusTitle", lag ? `Fix: ${lag.area}` : `Deepen: ${weak}`);
  setText("focusBody",
    lag
      ? `Ignore everything else this week. Close the ${lag.gap.toFixed(0)}-point gap in ${lag.area}. ${lag.fix_hint}`
      : `Your transcript is even — still lead drills on ${weak} until it is no longer the weakest topic.`
  );

  // Hire dial
  setHireDial(hs);
  let verdict="HOLD", reason="";
  if(!eligible){ verdict="NO ADVANCE"; reason="Attendance gate fails — most campus systems auto-reject before the panel."; }
  else if(hs>=80){ verdict="ADVANCE"; reason="Composite, interview and eligibility clear a first-round advance at service + mid-product bars."; }
  else if(hs>=60){ verdict="MAYBE"; reason="Borderline. One weak topic can flip the panel. Close it before the next drive."; }
  else { verdict="NO ADVANCE"; reason="Below the quiet cutoff most panels use. Enrol the 90-day plan before burning attempts."; }
  setText("hireVerdict", verdict);
  setText("hireScore", `${hs}/100 hire-confidence`);
  setText("hireReason", reason);

  // Cost of gap — illustrative CTC bands (INR)
  // Service base ~4.5L, product ~12L, premium ~18L — gap severity shifts expected band
  const base = eligible && o.score>=85 ? 1200000 : eligible && o.score>=70 ? 650000 : eligible ? 450000 : 0;
  const target = eligible ? (o.score>=70 ? 1400000 : 900000) : 650000;
  const gapCost = Math.max(0, target - base);
  const lagPenalty = (r.lagging_areas||[]).slice(0,3).reduce((s,x)=>s + x.gap*2500, 0);
  const total = Math.round(gapCost + lagPenalty);
  setText("costAmount", formatINR(total));
  setText("costNote",
    total===0
      ? "No material first-year opportunity cost flagged at current standing."
      : `Estimated first-year CTC left on the table vs a closed-gap peer in the same department. Not a salary promise — a pressure signal.`
  );
  $("#costBreakdown").innerHTML=[
    `<span>Band today · ₹${formatINR(base)}</span>`,
    `<span>Band if gaps close · ₹${formatINR(target)}</span>`,
    `<span>Lagging topics taxed · ₹${formatINR(lagPenalty)}</span>`
  ].join("");

  // Company matches
  const companies=[
    {name:"TCS / Infosys Ninja", need:60, weight:{comp:0.4, iv:0.3, cgpa:0.2, att:0.1}, note:"Mass service bar"},
    {name:"Deloitte / Accenture", need:72, weight:{comp:0.35, iv:0.4, cgpa:0.15, att:0.1}, note:"Consulting + tech"},
    {name:"Product mid-tier", need:82, weight:{comp:0.3, iv:0.5, cgpa:0.1, att:0.1}, note:"DSA + systems depth"},
    {name:"FAANG-track intern", need:92, weight:{comp:0.25, iv:0.55, cgpa:0.1, att:0.1}, note:"Elite bar — stretch"}
  ];
  $("#companyMatches").innerHTML=companies.map(c=>{
    let raw = o.score*c.weight.comp + iv.overall_score*10*c.weight.iv + a.cgpa*10*c.weight.cgpa + r.attendance_snapshot.percentage*c.weight.att;
    if(!eligible) raw *= 0.5;
    const match=Math.max(4, Math.min(99, Math.round(raw)));
    const pass=eligible && match>=c.need;
    return `<div class="match-card ${pass?"hot":"cold"}">
      <div class="match-pct">${match}%</div>
      <div>
        <strong>${esc(c.name)}</strong>
        <small>${esc(c.note)} · bar ${c.need}</small>
        <div class="match-bar"><i style="width:${match}%"></i></div>
        <em>${pass?"Likely shortlist":"Stretch / not yet"}</em>
      </div>
    </div>`;
  }).join("");

  // Letters
  const role = iv.role || "the role";
  const company = iv.company || "the firm";
  $("#rejectLetter").innerHTML=`<p>Dear ${esc(r.student_name)},</p>
    <p>Thank you for interviewing for <b>${esc(role)}</b> at ${esc(company)}. After review we will not be moving forward.</p>
    <p>Feedback on file: <b>${esc(weak)}</b> below panel standard${eligible?"":"; attendance eligibility also blocked screening"}.</p>
    <p>We encourage another attempt after a focused preparation cycle.</p>
    <p class="sign">— Campus recruiting</p>`;
  $("#offerLetter").innerHTML=`<p>Dear ${esc(r.student_name)},</p>
    <p>Congratulations. Contingent on clearing the remaining gates, we are pleased to advance you for <b>${esc(role)}</b>.</p>
    <p>What tipped the panel: strength in <b>${esc(strong)}</b>, plus visible closure of the former gap in <b>${esc(weak)}</b>.</p>
    <p>Next step: HR schedule within 5 business days.</p>
    <p class="sign">— Campus recruiting</p>`;

  // Projection chart
  const now=[o.score, iv.overall_score*10, a.assignment_average, a.assessment_average, r.attendance_snapshot.percentage];
  const projected=now.map((v,i)=>{
    // Study plan lifts weakest dimensions harder
    const boost = i===1 ? 12 : i===0 ? 8 : 6;
    return Math.min(100, +(v+boost).toFixed(1));
  });
  makeChart("projChart",{
    type:"line",
    data:{
      labels:["Composite","Interview×10","Assignments","Assessments","Attendance"],
      datasets:[
        {label:"Today", data:now, borderColor:WARN, backgroundColor:"rgba(138,90,18,0.12)", fill:true, tension:0.25, pointRadius:4},
        {label:"Day 90 (if plan holds)", data:projected, borderColor:ACCENT, backgroundColor:"rgba(31,92,77,0.12)", fill:true, tension:0.25, pointRadius:4}
      ]
    },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{legend:{position:"top", align:"end", labels:{boxWidth:12, font:{size:10}}}},
      scales:{y:{min:0, max:100, grid:{color:TRACK}}, x:{ticks:{font:{size:10}}, grid:{display:false}}}
    }
  });

  // Drill topic
  drillTopicKey = weak;
  setText("drillTopic", weak);
  pickDrillQuestion(false);

  // Battle card
  setText("battleName", r.student_name);
  setText("battleOpen", strong);
  setText("battleAvoid", weak);
  const topStrength = r.strengths?.[0];
  setText("battleProof", topStrength ? `${topStrength.title} — ${topStrength.evidence}` : `Lead with ${strong} and cite a scored answer ≥9.`);
  setText("battleClose", `If asked about ${weak}: admit the gap in one line, then show the drill plan and one improved answer.`);
  $("#battleTags").innerHTML=[
    `${o.letter} · ${o.status}`,
    r.performance_tier?.label,
    `${iv.overall_score}/10 panel`,
    eligible?"Eligible":"Not Eligible"
  ].filter(Boolean).map(t=>`<span class="tag">${esc(t)}</span>`).join("");

  // Constellation
  const nodes=[
    ...r.dimension_scores.map(d=>({name:d.name.split(" ")[0], score:d.score})),
    ...topicAverages(iv.questions).slice(0,5).map(t=>({name:t.topic.split(" ")[0], score:t.avg*10}))
  ].slice(0,10);
  const cx=200, cy=120, R=90;
  $("#constellation").innerHTML = nodes.map((n,i)=>{
    const ang = (i/nodes.length)*Math.PI*2 - Math.PI/2;
    const x = cx + Math.cos(ang)*R;
    const y = cy + Math.sin(ang)*R;
    const size = 10 + (n.score/100)*22;
    const op = 0.35 + (n.score/100)*0.65;
    return `<span class="star" style="left:${x}px;top:${y}px;width:${size}px;height:${size}px;opacity:${op}" title="${esc(n.name)} ${Math.round(n.score)}">
      <i></i><b>${esc(n.name)}</b>
    </span>`;
  }).join("") + `<span class="star core" style="left:${cx}px;top:${cy}px"><i></i><b>${esc(r.student_name.split(" ")[0])}</b></span>`;
}

function pickDrillQuestion(announce){
  if(!report) return;
  const bank = DRILL_BANK[drillTopicKey] || DRILL_BANK["Interview Performance"];
  const item = bank[Math.floor(Math.random()*bank.length)];
  setText("drillQuestion", item.q);
  setText("drillHint", announce ? `Hint: ${item.hint}` : "Hint unlocks when the timer hits 20s — or click Next.");
  return item;
}

function startDrill(){
  if(!report) return;
  clearInterval(drillTimer);
  drillLeft=60;
  setText("drillClock", String(drillLeft));
  pickDrillQuestion(false);
  $("#drillCard")?.classList?.add("live");
  drillTimer=setInterval(()=>{
    drillLeft-=1;
    setText("drillClock", String(Math.max(0,drillLeft)));
    if(drillLeft===20){
      const bank = DRILL_BANK[drillTopicKey] || DRILL_BANK["Interview Performance"];
      // show hint for current displayed question roughly
      const hintEl=$("#drillHint");
      if(hintEl && !hintEl.textContent.startsWith("Hint:")){
        // re-pick to get a hint pair — keep question, just reveal generic
        hintEl.textContent="Hint: Definition → Example → Trade-off. Speak it in 60 seconds.";
      }
    }
    if(drillLeft<=0){
      clearInterval(drillTimer);
      setText("drillHint","Time. Record yourself and score honesty 1–10. Then hit Next.");
    }
  },1000);
}

function speakRecommendation(){
  if(!report || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(
    `${report.student_name}. ${report.performance_tier.label}. ${report.counselor_recommendation}`
  );
  u.rate=1; u.pitch=1;
  window.speechSynthesis.speak(u);
}

function printBattleCard(){
  const card=$("#battleCard");
  if(!card) return;
  document.body.classList.add("print-battle");
  window.print();
  setTimeout(()=>document.body.classList.remove("print-battle"), 400);
}

$("#loadDemo").onclick=()=>getDemo("strong");
$("#runDemo2").onclick=()=>getDemo("strong");
$("#runAtRisk").onclick=()=>getDemo("at-risk");
$("#demoStrong").onclick=()=>getDemo("strong");
$("#demoAtRisk").onclick=()=>getDemo("at-risk");
$("#runCustom").onclick=runCustom;
$("#printReport").onclick=printFinalReport;
$("#exportJson").onclick=exportReport;
$("#exportMarkdown")?.addEventListener("click", exportMarkdown);
$("#exportMarkdown2")?.addEventListener("click", exportMarkdown);
$("#printFinal")?.addEventListener("click", printFinalReport);
$("#simReset").onclick=()=>syncSimulatorFromReport(report);
$("#simRecommend")?.addEventListener("click", applyRecommendedLevers);
["simInterview","simAssign","simAttend","simDsa","simComms"].forEach(id=>{
  const el=$("#"+id); if(el) el.addEventListener("input", updateSimulator);
});
$("#speakRec")?.addEventListener("click", speakRecommendation);
$("#drillStart")?.addEventListener("click", startDrill);
$("#drillNext")?.addEventListener("click", ()=>{ pickDrillQuestion(true); if(drillLeft<=0||!drillTimer) startDrill(); });
$("#printBattle")?.addEventListener("click", printBattleCard);

$("#downloadTemplate").onclick=()=>{const t={ "student.json":{"student_id":"STU001","name":"Student Name","email":"student@example.com","phone_number":"9876543210","department":"CSE","year":3,"semester":5,"cgpa":8.0},"interview.json":{"student_id":"STU001","student_name":"Student Name","interview_date":"2026-09-20","company":"Example Corp","job_role":"Software Engineer Intern","overall_score":8,"questions":[{"question":"Tell me about yourself.","student_answer":"...","score":8,"feedback":"..."}],"interviewer_observation":{"communication":"Good"},"strengths":["..."],"weaknesses":["..."],"overall_feedback":"..."},"assignment.json":{"student_id":"STU001","assignments":[{"assignment_id":"A101","title":"Project","subject":"Python","marks":85,"max_marks":100,"submission_status":"On Time","feedback":"..."}]},"assessment.json":{"student_id":"STU001","assessments":[{"assessment_id":"AS101","subject":"Python","score":85,"grade":"A"}]},"attendance.json":{"student_id":"STU001","month":"September","working_days":20,"present_days":19,"absent_days":1,"leave_days":0,"attendance_percentage":95,"status":"Eligible"}};const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(t,null,2)],{type:"application/json"}));a.download="student-pipeline-input-template.json";a.click();};
$("#bundleFile").onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const b=JSON.parse(await f.text());fillSources(b);setRun("Bundle imported. Review inputs, then run pipeline.");}catch(err){setRun("Bundle import failed: "+err.message,false,true)}};
$$(".nav-btn").forEach(b=>b.onclick=()=>{
  $$(".nav-btn").forEach(x=>x.classList.remove("active"));
  b.classList.add("active");
  document.getElementById(b.dataset.target)?.scrollIntoView({behavior:"smooth"});
});

// Keep navigation synchronized with the report section currently in view.
const navTargets = $$(".nav-btn")
  .map(btn=>({btn, section:document.getElementById(btn.dataset.target)}))
  .filter(x=>x.section);
if("IntersectionObserver" in window){
  const sectionObserver = new IntersectionObserver(entries=>{
    const visible = entries
      .filter(entry=>entry.isIntersecting)
      .sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];
    if(!visible) return;
    navTargets.forEach(({btn,section})=>
      btn.classList.toggle("active", section === visible.target)
    );
  }, {rootMargin:"-18% 0px -62% 0px", threshold:[0,.15,.4]});
  navTargets.forEach(({section})=>sectionObserver.observe(section));
}
getDemo("strong");


/* ── Study Planner theme controls ─────────────────────────────
   Presentation-only: light/dark preference, no report/backend changes.
*/
(function initThemeControls(){
  const root = document.documentElement;
  const body = document.body;
  const lightBtn = document.getElementById("lightMode");
  const darkBtn = document.getElementById("darkMode");
  if(!lightBtn || !darkBtn) return;

  const applyTheme = (theme) => {
    const dark = theme === "dark";
    body.classList.toggle("dark-mode", dark);
    root.setAttribute("data-theme", dark ? "dark" : "light");
    lightBtn.classList.toggle("active", !dark);
    darkBtn.classList.toggle("active", dark);
    try { localStorage.setItem("studyPlannerTheme", dark ? "dark" : "light"); } catch(e) {}
  };

  let saved = "light";
  try { saved = localStorage.getItem("studyPlannerTheme") || "light"; } catch(e) {}
  applyTheme(saved === "dark" ? "dark" : "light");

  lightBtn.addEventListener("click", () => applyTheme("light"));
  darkBtn.addEventListener("click", () => applyTheme("dark"));
})();

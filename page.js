"use client";

import { useMemo, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const blankRow = (i) => ({
  item_no: i,
  description: "",
  element_type: "room",
  numbers: 1,
  length: 0,
  width: 0,
  height: 0,
  unit: "m2",
  formula: "",
  quantity: 0,
  source: "manual",
  confidence: null,
  page: 1,
  verified: false
});

function calc(row) {
  const n = Number(row.numbers) || 0;
  const l = Number(row.length) || 0;
  const w = Number(row.width) || 0;
  const h = Number(row.height) || 0;

  if (row.unit === "m2") return n * l * w;
  if (row.unit === "m3") return n * l * w * h;
  if (row.unit === "m") return n * l;
  if (row.unit === "nos") return n;
  return Number(row.quantity) || 0;
}

export default function Home() {
  const [project, setProject] = useState("My Construction Project");
  const [scale, setScale] = useState("1:100");
  const [units, setUnits] = useState("mm");
  const [drawing, setDrawing] = useState(null);
  const [rows, setRows] = useState([blankRow(1)]);
  const [busy, setBusy] = useState(false);
  const [download, setDownload] = useState("");
  const [error, setError] = useState("");

  const total = useMemo(
    () => rows.reduce((sum, row) => sum + calc(row), 0),
    [rows]
  );

  async function upload(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Please select a PDF drawing.");
      return;
    }

    setBusy(true);
    setError("");
    setDownload("");

    try {
      const form = new FormData();
      form.append("file", file);

      const res = await fetch(`${API}/api/drawings/upload`, {
        method: "POST",
        body: form
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setDrawing(data);
    } catch (err) {
      setError(err.message || "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  function updateRow(index, key, value) {
    setRows((old) =>
      old.map((r, i) => i === index ? { ...r, [key]: value } : r)
    );
  }

  function addRow() {
    setRows((old) => [...old, blankRow(old.length + 1)]);
  }

  function removeRow(index) {
    setRows((old) => old.filter((_, i) => i !== index).map((r, i) => ({ ...r, item_no: i + 1 })));
  }

  async function exportExcel() {
    setBusy(true);
    setError("");
    setDownload("");

    try {
      const measurements = rows.map((r) => ({
        ...r,
        numbers: Number(r.numbers) || 0,
        length: Number(r.length) || 0,
        width: Number(r.width) || 0,
        height: Number(r.height) || 0,
        quantity: calc(r),
        page: Number(r.page) || 1
      }));

      const res = await fetch(`${API}/api/takeoff/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_name: project,
          scale,
          drawing_units: units,
          measurements
        })
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setDownload(`${API}${data.download_url}`);
    } catch (err) {
      setError(err.message || "Excel export failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ minHeight: "100vh" }}>
      <header style={{ background: "#17212b", color: "white", padding: "18px 28px" }}>
        <div style={{ fontSize: 22, fontWeight: 700 }}>AI Quantity Takeoff</div>
        <div style={{ opacity: 0.75, marginTop: 4 }}>
          Architectural drawing measurement & QS takeoff MVP
        </div>
      </header>

      <section style={{ padding: 22 }}>
        <div style={{
          display: "grid",
          gridTemplateColumns: "300px 1fr 440px",
          gap: 18,
          alignItems: "start"
        }}>
          <aside style={card}>
            <h3>Project</h3>

            <label>Project Name</label>
            <input value={project} onChange={e => setProject(e.target.value)} style={input}/>

            <label>Drawing Scale</label>
            <select value={scale} onChange={e => setScale(e.target.value)} style={input}>
              <option>1:50</option>
              <option>1:75</option>
              <option>1:100</option>
              <option>1:200</option>
            </select>

            <label>Drawing Units</label>
            <select value={units} onChange={e => setUnits(e.target.value)} style={input}>
              <option>mm</option>
              <option>m</option>
              <option>inch</option>
              <option>ft</option>
            </select>

            <label style={uploadLabel}>
              {busy ? "Processing..." : "Upload PDF Drawing"}
              <input type="file" accept=".pdf" onChange={upload} hidden />
            </label>

            {drawing && (
              <div style={{ marginTop: 14, fontSize: 13 }}>
                <b>{drawing.filename}</b>
                <div>{drawing.pages} page(s)</div>
                <div style={{ marginTop: 8 }}>
                  Dimension candidates found: {drawing.dimension_candidates.length}
                </div>
              </div>
            )}

            {error && <div style={{ color: "#b00020", marginTop: 14 }}>{error}</div>}
          </aside>

          <section style={card}>
            <h3>Drawing Viewer</h3>
            {drawing ? (
              <iframe
                src={`${API}/api/drawings/${drawing.drawing_id}/file`}
                style={{ width: "100%", height: "720px", border: "1px solid #ddd" }}
                title="Drawing PDF"
              />
            ) : (
              <div style={empty}>
                Upload a PDF drawing to view it here.
              </div>
            )}
          </section>

          <section style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>Measurement Sheet</h3>
              <button onClick={addRow}>+ Add</button>
            </div>

            <div style={{ overflowX: "auto", marginTop: 12 }}>
              <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
                <thead>
                  <tr>
                    {["Item", "Description", "Nos", "L", "W", "H/D", "Unit", "Qty", "✓"].map(h =>
                      <th key={h} style={th}>{h}</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i}>
                      <td style={td}>{i + 1}</td>
                      <td style={td}>
                        <input
                          value={row.description}
                          onChange={e => updateRow(i, "description", e.target.value)}
                          style={smallInput}
                          placeholder="Room / Wall / Beam"
                        />
                      </td>
                      <td style={td}><input type="number" value={row.numbers} onChange={e => updateRow(i, "numbers", e.target.value)} style={numInput}/></td>
                      <td style={td}><input type="number" value={row.length} onChange={e => updateRow(i, "length", e.target.value)} style={numInput}/></td>
                      <td style={td}><input type="number" value={row.width} onChange={e => updateRow(i, "width", e.target.value)} style={numInput}/></td>
                      <td style={td}><input type="number" value={row.height} onChange={e => updateRow(i, "height", e.target.value)} style={numInput}/></td>
                      <td style={td}>
                        <select value={row.unit} onChange={e => updateRow(i, "unit", e.target.value)} style={smallInput}>
                          <option value="m2">m²</option>
                          <option value="m3">m³</option>
                          <option value="m">m</option>
                          <option value="nos">Nos</option>
                        </select>
                      </td>
                      <td style={{...td, fontWeight: 700}}>{calc(row).toFixed(3)}</td>
                      <td style={td}>
                        <input type="checkbox" checked={row.verified} onChange={e => updateRow(i, "verified", e.target.checked)}/>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ marginTop: 16, padding: 12, background: "#f0f3f6", fontWeight: 700 }}>
              Current total: {total.toFixed(3)}
            </div>

            <button
              onClick={exportExcel}
              disabled={busy || rows.length === 0}
              style={primaryButton}
            >
              {busy ? "Generating..." : "Export Formula-Driven Excel"}
            </button>

            {download && (
              <a href={download} style={{ display: "block", marginTop: 12 }}>
                Download Quantity Takeoff Excel
              </a>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

const card = {
  background: "white",
  border: "1px solid #e1e5e9",
  borderRadius: 10,
  padding: 16,
  boxShadow: "0 2px 8px rgba(0,0,0,.04)"
};

const input = {
  width: "100%",
  boxSizing: "border-box",
  padding: 9,
  margin: "6px 0 14px",
  border: "1px solid #cfd5da",
  borderRadius: 6
};

const smallInput = {
  width: "100%",
  boxSizing: "border-box",
  padding: 5,
  border: "1px solid #cfd5da",
  borderRadius: 4
};

const numInput = {
  width: 58,
  boxSizing: "border-box",
  padding: 5,
  border: "1px solid #cfd5da",
  borderRadius: 4
};

const uploadLabel = {
  display: "block",
  padding: "11px 12px",
  background: "#e9eef3",
  borderRadius: 6,
  cursor: "pointer",
  textAlign: "center",
  fontWeight: 700
};

const primaryButton = {
  width: "100%",
  marginTop: 18,
  padding: 12,
  border: 0,
  borderRadius: 6,
  background: "#17212b",
  color: "white",
  cursor: "pointer",
  fontWeight: 700
};

const th = {
  padding: 7,
  borderBottom: "2px solid #ddd",
  textAlign: "left"
};

const td = {
  padding: 5,
  borderBottom: "1px solid #eee"
};

const empty = {
  height: 720,
  display: "grid",
  placeItems: "center",
  color: "#777",
  background: "#fafafa"
};

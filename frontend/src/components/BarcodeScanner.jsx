import { useState, useEffect, useRef, useCallback } from 'react'
import { BrowserMultiFormatReader } from '@zxing/browser'
import styles from './BarcodeScanner.module.css'

const API = '/api/inventory'

const LOCATION_LABELS = {
  pantry: 'Pantry Cupboard',
  fridge_inside: 'Inside Fridge',
  freezer_inside: 'Inside Freezer',
  fridge_outside: 'Outside Fridge',
  freezer_outside: 'Outside Freezer',
}

// Continuous decode fires many times/sec on the same code — ignore a repeat
// of the same barcode within this window.
const DEDUPE_MS = 2000

export default function BarcodeScanner({ locations, defaultLocation, onClose, onAdded }) {
  const videoRef = useRef(null)
  const readerRef = useRef(null)
  const controlsRef = useRef(null)
  const lastScanRef = useRef({ code: '', t: 0 })

  const [status, setStatus] = useState('starting') // starting | scanning | error
  const [errorMsg, setErrorMsg] = useState('')
  const [manual, setManual] = useState(false)
  const [pending, setPending] = useState(null) // {barcode, name, brand, found}
  const [location, setLocation] = useState(defaultLocation || (locations?.[0] ?? 'pantry'))
  const [mode, setMode] = useState('count') // count | level
  const [count, setCount] = useState(1)
  const [restock, setRestock] = useState('')
  const [manualName, setManualName] = useState('')
  const [added, setAdded] = useState([]) // running list of "name (action)"
  const [rapid, setRapid] = useState(false) // continuous mode: auto-add known items, no confirm
  const [receipt, setReceipt] = useState(false) // receipt-photo mode
  const [receiptStatus, setReceiptStatus] = useState('idle') // idle | reading | review | error
  const [receiptErr, setReceiptErr] = useState('')
  const [receiptItems, setReceiptItems] = useState([]) // [{name, quantity, keep}]

  // handleBarcode is a stable useCallback; rapid mode and the current location
  // are read via refs so the decode callback always sees the latest values.
  const rapidRef = useRef(rapid)
  const locationRef = useRef(location)
  useEffect(() => { rapidRef.current = rapid }, [rapid])
  useEffect(() => { locationRef.current = location }, [location])

  // Add a found item directly (count 1, scan location) — the continuous path.
  const autoAdd = useCallback(async (name) => {
    const finalName = (name || '').trim()
    if (!finalName) return
    const loc = locationRef.current
    try {
      const res = await fetch(`${API}/scan-add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: finalName, location: loc, track_mode: 'count', count: 1 }),
      })
      const data = await res.json()
      const verb = data.action === 'restocked' ? 'restocked'
        : data.action === 'incremented' ? 'added to' : 'added to'
      setAdded(a => [`${finalName} — ${verb} ${LOCATION_LABELS[loc] || loc}`, ...a])
      onAdded?.(data)
    } catch { /* lookup/add failure just skips this beep */ }
  }, [onAdded])

  const handleBarcode = useCallback(async (code) => {
    const now = Date.now()
    if (code === lastScanRef.current.code && now - lastScanRef.current.t < DEDUPE_MS) return
    lastScanRef.current = { code, t: now }
    // Pause further scanning while we resolve + confirm this one.
    setStatus('resolving')
    try {
      const res = await fetch(`${API}/lookup/${encodeURIComponent(code)}`)
      const data = await res.json()
      const found = !!data.found
      const name = found ? (data.brand ? `${data.name} (${data.brand})` : data.name) : ''
      // Continuous mode: a recognised item is added straight away, no card.
      // An unrecognised code still stops for a name — we can't auto-add a blank.
      if (rapidRef.current && found) {
        await autoAdd(name)
        setStatus('scanning')
        return
      }
      setPending({ barcode: code, name, found })
    } catch {
      setPending({ barcode: code, name: '', found: false })
    }
  }, [autoAdd])

  useEffect(() => {
    if (manual || receipt) return
    let cancelled = false
    const reader = new BrowserMultiFormatReader()
    readerRef.current = reader
    setStatus('starting')
    reader
      .decodeFromVideoDevice(undefined, videoRef.current, (result) => {
        if (cancelled || !result) return
        setStatus('scanning')
        handleBarcode(result.getText())
      })
      .then((controls) => {
        if (cancelled) { controls.stop(); return }
        controlsRef.current = controls
        setStatus('scanning')
      })
      .catch((err) => {
        if (cancelled) return
        setStatus('error')
        setErrorMsg(
          err?.name === 'NotAllowedError'
            ? 'Camera permission denied. Allow camera access and reopen.'
            : (err?.message || 'Could not start the camera.')
        )
      })
    return () => {
      cancelled = true
      try { controlsRef.current?.stop() } catch { /* already stopped */ }
    }
  }, [manual, receipt, handleBarcode])

  async function confirmAdd(name) {
    const finalName = (name || '').trim()
    if (!finalName) return
    const qty = mode === 'count' ? Math.max(1, parseInt(count, 10) || 1) : 1
    const res = await fetch(`${API}/scan-add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: finalName, location, track_mode: mode,
        count: qty, restock: mode === 'level' ? restock.trim() : '',
      }),
    })
    const data = await res.json()
    const verb = data.action === 'restocked' ? 'restocked'
      : data.action === 'incremented' ? 'added to' : 'added to'
    setAdded(a => [`${finalName} — ${verb} ${LOCATION_LABELS[location] || location}`, ...a])
    onAdded?.(data)
    // Reset for next item, keep scanning.
    setPending(null); setMode('count'); setCount(1); setRestock(''); setManualName('')
    if (!manual) setStatus('scanning')
  }

  function skip() {
    setPending(null); setMode('count'); setCount(1); setRestock('')
    if (!manual) setStatus('scanning')
  }

  // Receipt mode: read the chosen photo, send to the OCR endpoint, show a
  // reviewable checklist. Nothing is saved until the user confirms.
  async function onReceiptFile(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-picking the same file
    if (!file) return
    setReceiptErr(''); setReceiptStatus('reading')
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const fr = new FileReader()
        fr.onload = () => resolve(fr.result)
        fr.onerror = () => reject(fr.error)
        fr.readAsDataURL(file)
      })
      const res = await fetch(`${API}/receipt-scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: dataUrl }),
      })
      const data = await res.json()
      if (!res.ok) {
        setReceiptErr(data.error || 'Could not read the receipt.')
        setReceiptStatus('error')
        return
      }
      const items = (data.items || []).map(it => ({
        name: it.name, quantity: it.quantity || 1, keep: true,
      }))
      if (items.length === 0) {
        setReceiptErr('No items found on that photo — try a clearer shot.')
        setReceiptStatus('error')
        return
      }
      setReceiptItems(items)
      setReceiptStatus('review')
    } catch {
      setReceiptErr('Could not read that image.')
      setReceiptStatus('error')
    }
  }

  function setReceiptItem(idx, patch) {
    setReceiptItems(list => list.map((it, i) => i === idx ? { ...it, ...patch } : it))
  }

  async function addReceiptItems() {
    const keep = receiptItems.filter(it => it.keep && it.name.trim())
    for (const it of keep) {
      try {
        const res = await fetch(`${API}/scan-add`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: it.name.trim(), location,
            track_mode: 'count', count: Math.max(1, parseInt(it.quantity, 10) || 1),
          }),
        })
        const data = await res.json()
        setAdded(a => [`${it.name.trim()} — added to ${LOCATION_LABELS[location] || location}`, ...a])
        onAdded?.(data)
      } catch { /* skip a failed line, keep going */ }
    }
    setReceiptItems([]); setReceiptStatus('idle')
  }

  return (
    <div className={styles.overlay} data-testid="scanner">
      <div className={styles.panel}>
        <div className={styles.header}>
          <span>📷 Scan to add</span>
          <button className={styles.closeBtn} onClick={onClose} data-testid="scanner-close">✕</button>
        </div>

        <div className={styles.modeRow}>
          <button
            className={(!manual && !receipt) ? styles.modeActive : styles.modeBtn}
            onClick={() => { setManual(false); setReceipt(false) }}
          >Barcode</button>
          <button
            className={receipt ? styles.modeActive : styles.modeBtn}
            onClick={() => { setReceipt(true); setManual(false); try { controlsRef.current?.stop() } catch { /* noop */ } }}
            data-testid="scanner-receipt"
          >Receipt</button>
          <button
            className={manual ? styles.modeActive : styles.modeBtn}
            onClick={() => { setManual(true); setReceipt(false); try { controlsRef.current?.stop() } catch { /* noop */ } }}
            data-testid="scanner-manual"
          >Manual</button>
        </div>

        {/* Receipt mode: pick/snap a photo, review the parsed items, bulk-add */}
        {receipt && (
          <div className={styles.confirm} data-testid="receipt-panel">
            <label className={styles.field}>
              File into
              <select value={location} onChange={e => setLocation(e.target.value)}>
                {locations.map(l => <option key={l} value={l}>{LOCATION_LABELS[l] || l}</option>)}
              </select>
            </label>

            {receiptStatus !== 'review' && (
              <>
                <label className={styles.addBtn} style={{ textAlign: 'center', cursor: 'pointer' }}>
                  📄 {receiptStatus === 'reading' ? 'Reading…' : 'Take / choose a receipt photo'}
                  <input
                    type="file"
                    accept="image/*"
                    capture="environment"
                    style={{ display: 'none' }}
                    disabled={receiptStatus === 'reading'}
                    onChange={onReceiptFile}
                    data-testid="receipt-file"
                  />
                </label>
                <p className={styles.notFound}>
                  One photo of your till receipt → a list you tick and add. Items all go to the location above.
                </p>
                {receiptStatus === 'error' && <p className={styles.notFound} style={{ color: 'var(--color-danger)' }}>{receiptErr}</p>}
              </>
            )}

            {receiptStatus === 'review' && (
              <>
                <p className={styles.foundName}>{receiptItems.filter(i => i.keep).length} of {receiptItems.length} items selected</p>
                <ul className={styles.addedList} style={{ maxHeight: '45vh' }}>
                  {receiptItems.map((it, idx) => (
                    <li key={idx} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '2px 0' }}>
                      <input
                        type="checkbox"
                        checked={it.keep}
                        onChange={e => setReceiptItem(idx, { keep: e.target.checked })}
                      />
                      <input
                        className={styles.input}
                        style={{ flex: 1 }}
                        value={it.name}
                        onChange={e => setReceiptItem(idx, { name: e.target.value })}
                      />
                      <input
                        type="number"
                        min="1"
                        className={styles.input}
                        style={{ width: '3.2rem' }}
                        value={it.quantity}
                        onChange={e => setReceiptItem(idx, { quantity: e.target.value })}
                      />
                    </li>
                  ))}
                </ul>
                <div className={styles.actions}>
                  <button className={styles.addBtn} onClick={addReceiptItems} data-testid="receipt-add">
                    Add selected
                  </button>
                  <button className={styles.skipBtn} onClick={() => { setReceiptItems([]); setReceiptStatus('idle') }}>
                    Discard
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {!manual && !receipt && (
          <label className={styles.checkRow} data-testid="rapid-toggle">
            <input
              type="checkbox"
              checked={rapid}
              onChange={e => setRapid(e.target.checked)}
            />
            Continuous — add recognised items instantly, no tap (count 1 each)
          </label>
        )}

        {!manual && !receipt && (
          <div className={styles.videoWrap}>
            <video ref={videoRef} className={styles.video} muted playsInline />
            <div className={styles.reticle} />
            <div className={styles.status}>
              {status === 'starting' && 'Starting camera…'}
              {status === 'scanning' && (rapid ? 'Continuous — scan items one after another' : 'Point a barcode at the camera')}
              {status === 'resolving' && 'Looking up…'}
              {status === 'error' && errorMsg}
            </div>
          </div>
        )}

        {/* Confirm card for a scanned/looked-up item */}
        {pending && (
          <div className={styles.confirm} data-testid="scan-confirm">
            {pending.found ? (
              <p className={styles.foundName}>{pending.name}</p>
            ) : (
              <>
                <p className={styles.notFound}>Not recognised — type a name:</p>
                <input
                  className={styles.input}
                  placeholder="Item name"
                  value={manualName}
                  onChange={e => setManualName(e.target.value)}
                  autoFocus
                />
              </>
            )}
            <label className={styles.field}>
              Location
              <select value={location} onChange={e => setLocation(e.target.value)}>
                {locations.map(l => <option key={l} value={l}>{LOCATION_LABELS[l] || l}</option>)}
              </select>
            </label>
            <div className={styles.modeRow}>
              <button
                type="button"
                className={mode === 'count' ? styles.modeActive : styles.modeBtn}
                onClick={() => setMode('count')}
              >Count (cans)</button>
              <button
                type="button"
                className={mode === 'level' ? styles.modeActive : styles.modeBtn}
                onClick={() => setMode('level')}
              >Level (rice)</button>
            </div>
            {mode === 'count' ? (
              <label className={styles.field}>
                How many?
                <input
                  type="number"
                  min="1"
                  className={styles.input}
                  value={count}
                  onChange={e => setCount(e.target.value)}
                />
              </label>
            ) : (
              <input
                className={styles.input}
                placeholder="Restock text, e.g. 2L milk"
                value={restock}
                onChange={e => setRestock(e.target.value)}
              />
            )}
            <div className={styles.actions}>
              <button
                className={styles.addBtn}
                data-testid="scan-add"
                onClick={() => confirmAdd(pending.found ? pending.name : manualName)}
              >Add</button>
              <button className={styles.skipBtn} onClick={skip}>Skip</button>
            </div>
          </div>
        )}

        {/* Manual-only entry (no barcode) */}
        {manual && !pending && (
          <div className={styles.confirm}>
            <input
              className={styles.input}
              placeholder="Item name"
              value={manualName}
              onChange={e => setManualName(e.target.value)}
              autoFocus
            />
            <label className={styles.field}>
              Location
              <select value={location} onChange={e => setLocation(e.target.value)}>
                {locations.map(l => <option key={l} value={l}>{LOCATION_LABELS[l] || l}</option>)}
              </select>
            </label>
            <div className={styles.modeRow}>
              <button
                type="button"
                className={mode === 'count' ? styles.modeActive : styles.modeBtn}
                onClick={() => setMode('count')}
              >Count (cans)</button>
              <button
                type="button"
                className={mode === 'level' ? styles.modeActive : styles.modeBtn}
                onClick={() => setMode('level')}
              >Level (rice)</button>
            </div>
            {mode === 'count' ? (
              <label className={styles.field}>
                How many?
                <input
                  type="number"
                  min="1"
                  className={styles.input}
                  value={count}
                  onChange={e => setCount(e.target.value)}
                />
              </label>
            ) : (
              <input
                className={styles.input}
                placeholder="Restock text, e.g. 2L milk"
                value={restock}
                onChange={e => setRestock(e.target.value)}
              />
            )}
            <div className={styles.actions}>
              <button
                className={styles.addBtn}
                data-testid="manual-add"
                onClick={() => confirmAdd(manualName)}
              >Add</button>
            </div>
          </div>
        )}

        {added.length > 0 && (
          <ul className={styles.addedList}>
            {added.map((a, i) => <li key={i}>✓ {a}</li>)}
          </ul>
        )}
      </div>
    </div>
  )
}

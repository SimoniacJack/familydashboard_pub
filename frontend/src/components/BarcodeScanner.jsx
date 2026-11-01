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

  const handleBarcode = useCallback(async (code) => {
    const now = Date.now()
    if (code === lastScanRef.current.code && now - lastScanRef.current.t < DEDUPE_MS) return
    lastScanRef.current = { code, t: now }
    // Pause further scanning while we resolve + confirm this one.
    setStatus('resolving')
    try {
      const res = await fetch(`${API}/lookup/${encodeURIComponent(code)}`)
      const data = await res.json()
      setPending({
        barcode: code,
        name: data.found ? (data.brand ? `${data.name} (${data.brand})` : data.name) : '',
        found: !!data.found,
      })
    } catch {
      setPending({ barcode: code, name: '', found: false })
    }
  }, [])

  useEffect(() => {
    if (manual) return
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
  }, [manual, handleBarcode])

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

  return (
    <div className={styles.overlay} data-testid="scanner">
      <div className={styles.panel}>
        <div className={styles.header}>
          <span>📷 Scan to add</span>
          <button className={styles.closeBtn} onClick={onClose} data-testid="scanner-close">✕</button>
        </div>

        <div className={styles.modeRow}>
          <button
            className={!manual ? styles.modeActive : styles.modeBtn}
            onClick={() => setManual(false)}
          >Barcode</button>
          <button
            className={manual ? styles.modeActive : styles.modeBtn}
            onClick={() => { setManual(true); try { controlsRef.current?.stop() } catch { /* noop */ } }}
            data-testid="scanner-manual"
          >Manual</button>
        </div>

        {!manual && (
          <div className={styles.videoWrap}>
            <video ref={videoRef} className={styles.video} muted playsInline />
            <div className={styles.reticle} />
            <div className={styles.status}>
              {status === 'starting' && 'Starting camera…'}
              {status === 'scanning' && 'Point a barcode at the camera'}
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

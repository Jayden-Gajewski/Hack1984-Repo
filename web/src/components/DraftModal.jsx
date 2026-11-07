import React from 'react';

export default function DraftModal({ draft, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{draft.title}</h3>
        {draft.loading ? (
          <p>Finding the opt-out page…</p>
        ) : (
          <>
            {draft.link && (
              <p>
                Opt-out page: <a href={draft.link} target="_blank" rel="noreferrer">{draft.link}</a>{' '}
                <span className="muted">({draft.linkSource})</span>
              </p>
            )}
            <textarea readOnly value={draft.text} rows={16} />
            <button onClick={() => navigator.clipboard.writeText(draft.text)}>Copy</button>
          </>
        )}
        <button className="secondary" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

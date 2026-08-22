const dialog = document.getElementById('tx-dialog');
const form = document.getElementById('tx-form');
const type = document.getElementById('tx-type');
const asset = document.getElementById('tx-asset');
const amountLabel = document.getElementById('amount-label');
const eurLabel = document.getElementById('eur-label');
const eurHelp = document.getElementById('eur-help');

function fields() {
    if (!type) return;
    const transactionType = type.value;
    const selectedAsset = asset?.value || 'BTC';
    const isCrypto = ['Inkoop', 'Verkoop', 'Storting', 'Opname', 'Reward'].includes(transactionType);
    const show = {
        asset: isCrypto,
        amount: isCrypto,
        eur: ['Inkoop', 'Verkoop', 'EUR Storting', 'EUR Opname'].includes(transactionType),
        fee: ['Inkoop', 'Verkoop'].includes(transactionType),
        cost: transactionType === 'Storting'
    };
    document.querySelectorAll('[data-field]').forEach(element => {
        element.hidden = !show[element.dataset.field];
        const control = element.querySelector('input, select');
        if (control) control.required = Boolean(show[element.dataset.field]);
    });
    if (amountLabel) amountLabel.textContent = `${selectedAsset} hoeveelheid`;
    if (eurLabel) {
        eurLabel.textContent = transactionType === 'Inkoop'
            ? 'Totaalbedrag EUR (incl. kosten)'
            : transactionType === 'Verkoop' ? 'Netto-opbrengst EUR (na kosten)' : 'Bedrag EUR';
    }
    if (eurHelp) {
        eurHelp.textContent = transactionType === 'Inkoop'
            ? `Handelswaarde excl. kosten = totaalbedrag − kosten. Kostbasis incl. kosten = totaalbedrag.`
            : transactionType === 'Verkoop' ? `Bruto handelswaarde = netto-opbrengst + kosten. Kas en PnL gebruiken de netto-opbrengst.` : '';
    }
}

function setValue(name, value) {
    const input = form?.elements.namedItem(name);
    if (input) input.value = value ?? '';
}

function clearTransactionError() {
    document.getElementById('tx-error')?.remove();
    if (dialog) delete dialog.dataset.validationError;
}

function openNewTransaction() {
    clearTransactionError();
    form.reset();
    setValue('id', '');
    document.getElementById('tx-dialog-title').textContent = 'Nieuwe transactie';
    document.getElementById('save-transaction').textContent = 'Transactie opslaan';
    fields();
    dialog.showModal();
}

function openEditTransaction(transaction) {
    clearTransactionError();
    form.reset();
    Object.entries(transaction).forEach(([name, value]) => setValue(name, value));
    document.getElementById('tx-dialog-title').textContent = 'Transactie bewerken';
    document.getElementById('save-transaction').textContent = 'Wijzigingen opslaan';
    fields();
    dialog.showModal();
}

document.getElementById('add-transaction')?.addEventListener('click', openNewTransaction);
document.querySelectorAll('.edit-transaction').forEach(button => {
    button.addEventListener('click', () => openEditTransaction(JSON.parse(button.dataset.transaction)));
});
document.querySelectorAll('[data-close]').forEach(button => {
    button.addEventListener('click', () => button.closest('dialog').close());
});
document.querySelectorAll('.delete-transaction').forEach(deleteForm => {
    deleteForm.addEventListener('submit', event => {
        if (!window.confirm('Weet je zeker dat je deze transactie wilt verwijderen? Alle latere saldi en rendementen worden opnieuw berekend.')) {
            event.preventDefault();
        }
    });
});
document.querySelectorAll('.delete-asset').forEach(deleteForm => {
    deleteForm.addEventListener('submit', event => {
        if (!window.confirm('Weet je zeker dat je deze asset wilt verwijderen?')) {
            event.preventDefault();
        }
    });
});
type?.addEventListener('change', fields);
asset?.addEventListener('change', fields);
fields();
if (dialog?.dataset.validationError === 'true') {
    dialog.showModal();
}

const transactionFilterAsset = document.getElementById('transaction-filter-asset');
const transactionFilterType = document.getElementById('transaction-filter-type');
const transactionFilterClear = document.getElementById('transaction-filter-clear');
const transactionFilterStatus = document.getElementById('transaction-filter-status');
const transactionFilterEmpty = document.getElementById('transaction-filter-empty');
const transactionRows = [...document.querySelectorAll('[data-transaction-row]')];

function filterTransactions() {
    const selectedAsset = transactionFilterAsset?.value || '';
    const selectedType = transactionFilterType?.value || '';
    let visible = 0;
    transactionRows.forEach(row => {
        const matches = (!selectedAsset || row.dataset.asset === selectedAsset)
            && (!selectedType || row.dataset.type === selectedType);
        row.hidden = !matches;
        if (matches) visible += 1;
    });
    if (transactionFilterStatus) {
        transactionFilterStatus.textContent = `${visible} van ${transactionRows.length} transacties`;
    }
    if (transactionFilterEmpty) transactionFilterEmpty.hidden = visible !== 0;
    if (transactionFilterClear) transactionFilterClear.disabled = !selectedAsset && !selectedType;
}

transactionFilterAsset?.addEventListener('change', filterTransactions);
transactionFilterType?.addEventListener('change', filterTransactions);
transactionFilterClear?.addEventListener('click', () => {
    transactionFilterAsset.value = '';
    transactionFilterType.value = '';
    filterTransactions();
    transactionFilterAsset.focus();
});
filterTransactions();

document.querySelectorAll('.method-card').forEach(card => {
    card.addEventListener('toggle', () => {
        if (!card.open) return;
        document.querySelectorAll('.method-card[open]').forEach(other => {
            if (other !== card) other.open = false;
        });
    });
});

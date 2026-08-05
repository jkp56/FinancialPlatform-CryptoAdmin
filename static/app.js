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
            ? `${selectedAsset}-aankoopwaarde = totaalbedrag − kosten.`
            : transactionType === 'Verkoop' ? `Bruto ${selectedAsset}-verkoopwaarde = netto-opbrengst + kosten.` : '';
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
type?.addEventListener('change', fields);
asset?.addEventListener('change', fields);
fields();
if (dialog?.dataset.validationError === 'true') {
    dialog.showModal();
}

document.querySelectorAll('.method-card').forEach(card => {
    card.addEventListener('toggle', () => {
        if (!card.open) return;
        document.querySelectorAll('.method-card[open]').forEach(other => {
            if (other !== card) other.open = false;
        });
    });
});

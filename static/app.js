async function salvarFatura() {
  try {
    const transportadora = document.getElementById("cad-transportadora").value;
    const numeroFatura = document.getElementById("cad-numero-fatura").value;
    const valor = parseFloat(
      document.getElementById("cad-valor").value.replace(".", "").replace(",", ".")
    );
    const dataVenc = document.getElementById("cad-data-vencimento").value;
    const status = document.getElementById("cad-status").value;
    const observacao = document.getElementById("cad-observacao").value;

    const payload = {
      transportadora,
      numero_fatura: numeroFatura,
      valor,
      data_vencimento: dataVenc,
      status,
      observacao,
    };

    const resp = await fetch("/faturas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const erro = await resp.text();
      alert("Erro ao salvar fatura: " + erro);
      return;
    }

    alert("Fatura salva com sucesso!");
    // atualizar lista / dashboard se quiser
  } catch (e) {
    console.error(e);
    alert("Erro inesperado ao salvar fatura.");
  }
}

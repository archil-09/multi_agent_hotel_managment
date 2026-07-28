(function(){
  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => [...root.querySelectorAll(sel)];

  const apiInput = $('#apiBase');
  const savedBase = localStorage.getItem('hotelAgentApiBase');
  if (savedBase) apiInput.value = savedBase;
  apiInput.addEventListener('change', () => {
    localStorage.setItem('hotelAgentApiBase', apiInput.value.trim());
    checkConnection();
  });

  const staffKeyInput = $('#staffKey');
  const savedKey = localStorage.getItem('hotelAgentStaffKey');
  if (savedKey) staffKeyInput.value = savedKey;
  staffKeyInput.addEventListener('change', () => {
    localStorage.setItem('hotelAgentStaffKey', staffKeyInput.value.trim());
    checkConnection();
  });

  function authHeaders(extra = {}){
    return { 'X-Staff-Key': staffKeyInput.value.trim(), ...extra };
  }

  function base(){ return apiInput.value.trim().replace(/\/$/, ''); }

  function showToast(msg, isError=false){
    const t = $('#toast');
    t.textContent = msg;
    t.classList.toggle('error', isError);
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), 3800);
  }

  function setLoading(btn, on){
    btn.classList.toggle('loading', on);
    btn.disabled = on;
  }

  // ---------------- nav ----------------
  $$('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      $$('.nav-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      $$('.page').forEach(p => p.classList.remove('active'));
      $('#page-' + item.dataset.page).classList.add('active');
    });
  });

  // ---------------- connection check ----------------
  async function checkConnection(){
    const dot = $('#connDot'), label = $('#connLabel');
    try{
      const res = await fetch(base() + '/', { method:'GET' });
      if (!res.ok) throw new Error();
      dot.className = 'conn-dot ok';
      label.textContent = 'connected';
    }catch(e){
      dot.className = 'conn-dot bad';
      label.textContent = 'unreachable';
    }
  }

  // ---------------- dashboard ----------------
  async function loadHotels(){
    const tbody = $('#hotelsTable tbody');
    try{
      const res = await fetch(base() + '/hotels', { headers: authHeaders() });
      const data = await res.json();
      $('#statHotels').textContent = data.length;
      if (!data.length){
        tbody.innerHTML = '<tr><td colspan="2" class="empty-state">No hotels yet.</td></tr>';
        return;
      }
      tbody.innerHTML = data.map(h => `<tr><td>${escapeHtml(h.name)}</td><td>${escapeHtml(h.address || '—')}</td></tr>`).join('');
    }catch(e){
      tbody.innerHTML = '<tr><td colspan="2" class="empty-state">Could not reach the API.</td></tr>';
      $('#statHotels').textContent = '–';
    }
  }

  async function loadBookings(){
    const tbody = $('#bookingsTable tbody');
    try{
      const res = await fetch(base() + '/bookings', { headers: authHeaders() });
      const data = await res.json();
      $('#statBookings').textContent = data.length;
      if (!data.length){
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No bookings yet.</td></tr>';
        return;
      }
      tbody.innerHTML = data.map(b => `
        <tr>
          <td>${escapeHtml(b.guest_name)}</td>
          <td>${escapeHtml(b.room_number)}</td>
          <td>${escapeHtml(b.hotel_name)}</td>
          <td>${formatDate(b.check_in)}</td>
          <td>${formatDate(b.check_out)}</td>
          <td><span class="badge ${escapeHtml((b.status||'').toLowerCase())}">${escapeHtml(b.status || '—')}</span></td>
        </tr>`).join('');
    }catch(e){
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Could not reach the API.</td></tr>';
      $('#statBookings').textContent = '–';
    }
  }

  function formatDate(d){
    if (!d) return '—';
    try{ return new Date(d).toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric'}); }
    catch(e){ return d; }
  }
  function escapeHtml(str){
    return String(str ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function highlightSql(sql){
    const kws = ['SELECT','FROM','WHERE','JOIN','LEFT','RIGHT','INNER','ON','AND','OR','ORDER BY','GROUP BY','LIMIT','AS','DESC','ASC','COUNT','SUM','AVG','IN','NOT','NULL','IS','BETWEEN','HAVING'];
    let out = escapeHtml(sql);
    kws.forEach(k => {
      const re = new RegExp('\\b' + k.replace(' ', '\\s+') + '\\b', 'gi');
      out = out.replace(re, m => `<span class="kw">${m.toUpperCase()}</span>`);
    });
    return out;
  }

  // ---------------- ask ----------------
  $('#askBtn').addEventListener('click', async () => {
    const q = $('#askInput').value.trim();
    if (!q) return showToast('Type a question first.', true);
    const btn = $('#askBtn');
    setLoading(btn, true);
    try{
      const res = await fetch(base() + '/ask', {
        method:'POST',
        headers: authHeaders({'Content-Type':'application/json'}),
        body: JSON.stringify({ question: q })
      });
      const data = await res.json();
      $('#askResult').classList.add('show');
      $('#askSql').innerHTML = highlightSql(data.generated_sql || '(no query returned)');

      if (data.error){
        $('#askResultWrap').innerHTML = `<div class="empty-state">${escapeHtml(data.error)}</div>`;
        return showToast(data.error, true);
      }
      renderResultTable(data.result || []);
    }catch(e){
      showToast('Request failed — check the API URL.', true);
    }finally{
      setLoading(btn, false);
    }
  });

  $('#askClear').addEventListener('click', () => {
    $('#askInput').value = '';
    $('#askResult').classList.remove('show');
  });

  function renderResultTable(rows){
    const wrap = $('#askResultWrap');
    if (!rows.length){
      wrap.innerHTML = '<div class="empty-state">Query ran successfully — no rows returned.</div>';
      return;
    }
    const cols = Object.keys(rows[0]);
    const thead = `<thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>`;
    const tbody = `<tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${escapeHtml(r[c])}</td>`).join('')}</tr>`).join('')}</tbody>`;
    wrap.innerHTML = `<table>${thead}${tbody}</table>`;
  }

  // ---------------- actions (structured forms, no LLM) ----------------
  let currentActionId = null;

  // tab switching
  $$('#actionTabs .form-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('#actionTabs .form-tab').forEach(t => t.classList.remove('active'));
      $$('.action-form').forEach(f => f.classList.remove('active'));
      tab.classList.add('active');
      $('#form-' + tab.dataset.form).classList.add('active');
      $('#actionPreviewBox').classList.remove('show');
      $('#actionOutcomeBox').classList.remove('show');
    });
  });

  async function populateSelect(selectEl, url, valueFn, labelFn, placeholder){
    try{
      const res = await fetch(base() + url, { headers: authHeaders() });
      const data = await res.json();
      if (!Array.isArray(data) || !data.length){
        selectEl.innerHTML = `<option value="">No options available</option>`;
        return;
      }
      selectEl.innerHTML = `<option value="">${placeholder}</option>` +
        data.map(item => `<option value="${escapeHtml(valueFn(item))}">${escapeHtml(labelFn(item))}</option>`).join('');
    }catch(e){
      selectEl.innerHTML = `<option value="">Could not load options</option>`;
    }
  }

  function loadActionFormOptions(){
    populateSelect($('#bookRoom'), '/rooms',
      r => r.room_number,
      r => `${r.room_number} — ${r.hotel_name} (${r.room_type_name}, ${r.status})`,
      'Select a room');
    populateSelect($('#cancelBooking'), '/bookings',
      b => b.booking_id,
      b => `#${b.booking_id} — ${b.guest_name}, Room ${b.room_number} (${b.status})`,
      'Select a booking');
    populateSelect($('#addRoomHotel'), '/hotels',
      h => h.name,
      h => h.name,
      'Select a hotel');
    populateSelect($('#updateRoomTypeSelect'), '/room-types',
      rt => JSON.stringify({hotel_name: rt.hotel_name, old_type_name: rt.name}),
      rt => `${rt.name} — ${rt.hotel_name} (₹${Number(rt.base_price).toLocaleString()}, max ${rt.max_occupancy})`,
      'Select a room type');
    populateSelect($('#saleHotel'), '/hotels', h => h.name, h => h.name, 'Select a hotel');
  }

  async function proposeAction(actionType, payload, endpoint){
    $('#actionOutcomeBox').classList.remove('show');
    try{
      const res = await fetch(base() + endpoint, {
        method:'POST',
        headers: authHeaders({'Content-Type':'application/json'}),
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.error){
        $('#actionPreviewBox').classList.remove('show');
        return showToast(data.error, true);
      }
      currentActionId = data.action_id;
      renderPreview(data.preview);
      $('#actionExpiry').textContent = data.message || '';
      $('#actionPreviewBox').classList.add('show');
    }catch(e){
      showToast('Request failed — check the API URL.', true);
    }
  }

  $('#bookBtn').addEventListener('click', async () => {
    const room = $('#bookRoom').value, guest = $('#bookGuest').value.trim();
    const checkIn = $('#bookCheckIn').value, checkOut = $('#bookCheckOut').value;
    if (!room || !guest || !checkIn || !checkOut) return showToast('Fill in all fields first.', true);
    const btn = $('#bookBtn'); setLoading(btn, true);
    await proposeAction('create_booking', { room_number: room, guest_name: guest, check_in: checkIn, check_out: checkOut }, '/action/book');
    setLoading(btn, false);
  });

  $('#cancelBtn').addEventListener('click', async () => {
    const bookingId = $('#cancelBooking').value;
    if (!bookingId) return showToast('Select a booking first.', true);
    const btn = $('#cancelBtn'); setLoading(btn, true);
    await proposeAction('cancel_booking', { booking_id: Number(bookingId) }, '/action/cancel');
    setLoading(btn, false);
  });

  $('#addRoomBtn').addEventListener('click', async () => {
    const hotel = $('#addRoomHotel').value, type = $('#addRoomType').value.trim();
    const number = $('#addRoomNumber').value.trim();
    const price = $('#addRoomPrice').value, occupancy = $('#addRoomOccupancy').value;
    if (!hotel || !type || !number || !price || !occupancy) return showToast('Fill in all fields first.', true);
    if (/[,/&;]| and /i.test(number)) {
      return showToast('Enter one room number at a time — add each room separately.', true);
    }
    const btn = $('#addRoomBtn'); setLoading(btn, true);
    await proposeAction('add_room', {
      hotel_name: hotel, room_type_name: type, room_number: number,
      base_price: Number(price), max_occupancy: Number(occupancy)
    }, '/action/add-room');
    setLoading(btn, false);
  });

  $('#updateRoomTypeBtn').addEventListener('click', async () => {
    const selected = $('#updateRoomTypeSelect').value;
    if (!selected) return showToast('Select a room type first.', true);
    const { hotel_name, old_type_name } = JSON.parse(selected);
    const newName = $('#updateRoomTypeName').value.trim();
    const newPrice = $('#updateRoomTypePrice').value;
    const newOccupancy = $('#updateRoomTypeOccupancy').value;
    if (!newName && !newPrice && !newOccupancy) return showToast('Set at least one field to change.', true);
    const btn = $('#updateRoomTypeBtn'); setLoading(btn, true);
    await proposeAction('update_room_type', {
      hotel_name, old_type_name,
      new_type_name: newName || null,
      new_price: newPrice ? Number(newPrice) : null,
      new_max_occupancy: newOccupancy ? Number(newOccupancy) : null
    }, '/action/update-room-type');
    setLoading(btn, false);
  });

  $('#saleBtn').addEventListener('click', async () => {
    const hotel = $('#saleHotel').value, amount = $('#saleAmount').value;
    const date = $('#saleDate').value, category = $('#saleCategory').value.trim();
    const enteredBy = $('#saleEnteredBy').value.trim();
    if (!hotel || !amount || !date || !enteredBy) return showToast('Fill in hotel, amount, date, and your name.', true);
    const btn = $('#saleBtn'); setLoading(btn, true);
    await proposeAction('record_daily_sale', {
      hotel_name: hotel, amount: Number(amount), sale_date: date,
      category: category || null, entered_by: enteredBy
    }, '/action/record-sale');
    setLoading(btn, false);
  });

  function renderPreview(preview){
    const card = $('#actionPreviewCard');
    const rows = Object.entries(preview)
      .filter(([,v]) => v !== null && v !== undefined && v !== '')
      .map(([k,v]) => `<div class="preview-row"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(v)}</span></div>`)
      .join('');
    card.innerHTML = rows;
  }

  $('#confirmBtn').addEventListener('click', async () => {
    if (!currentActionId) return;
    const btn = $('#confirmBtn');
    setLoading(btn, true);
    try{
      const res = await fetch(base() + '/action/confirm', {
        method:'POST',
        headers: authHeaders({'Content-Type':'application/json'}),
        body: JSON.stringify({ action_id: currentActionId })
      });
      const data = await res.json();
      $('#actionOutcomeBox').classList.add('show');
      const card = $('#actionOutcomeCard');
      if (data.error){
        card.innerHTML = `<span class="badge error">Error</span><p style="margin-top:10px;">${escapeHtml(data.error)}</p>`;
        showToast(data.error, true);
      }else{
        const label = data.booking_id ? `Booking #${data.booking_id} created.` :
                      data.cancelled_booking_id ? `Booking #${data.cancelled_booking_id} cancelled.` :
                      data.room_id ? `Room added (id #${data.room_id}).` :
                      data.room_type_id ? `Room type updated.` :
                      data.sale_id ? `Sale entry #${data.sale_id} recorded.` :
                      'Action completed.';
        card.innerHTML = `<span class="badge success">Success</span><p style="margin-top:10px;">${escapeHtml(label)}</p>`;
        showToast(label);
        $('#actionPreviewBox').classList.remove('show');
        currentActionId = null;
        loadBookings();
        loadActionFormOptions();
      }
    }catch(e){
      showToast('Request failed — check the API URL.', true);
    }finally{
      setLoading(btn, false);
    }
  });

  $('#discardBtn').addEventListener('click', () => {
    currentActionId = null;
    $('#actionPreviewBox').classList.remove('show');
  });


  // ---------------- HR (manager-gated) ----------------
  const savedManagerKey = sessionStorage.getItem('hotelAgentManagerKey');
  let managerUnlocked = false;
  let currentManagerKey = '';

  function hrAuthHeaders(extra = {}){
    return { 'X-Manager-Key': currentManagerKey, ...extra };
  }

  async function tryUnlockHr(key){
    currentManagerKey = key;
    try{
      const res = await fetch(base() + '/hr/employees', { headers: hrAuthHeaders() });
      if (!res.ok) throw new Error('unauthorized');
      managerUnlocked = true;
      sessionStorage.setItem('hotelAgentManagerKey', key);
      $('#hrGate').style.display = 'none';
      $('#hrContent').classList.add('unlocked');
      loadEmployees();
      loadPayrollStatus();
      loadSalesSummary();
      loadAuditLog();
      loadHrFormOptions();
    }catch(e){
      managerUnlocked = false;
      $('#hrGateError').textContent = 'Incorrect manager key or API unreachable.';
      $('#hrGateError').style.display = 'block';
    }
  }

  $('#hrUnlockBtn').addEventListener('click', () => {
    const key = $('#hrKeyInput').value.trim();
    if (!key) return;
    tryUnlockHr(key);
  });
  $('#hrKeyInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('#hrUnlockBtn').click();
  });
  $('#hrLockBtn').addEventListener('click', () => {
    managerUnlocked = false;
    sessionStorage.removeItem('hotelAgentManagerKey');
    managerKeyInput.value = '';
    $('#hrGate').style.display = 'block';
    $('#hrContent').classList.remove('unlocked');
    $('#hrKeyInput').value = '';
  });

  async function loadEmployees(){
    const tbody = $('#employeesTable tbody');
    try{
      const res = await fetch(base() + '/hr/employees', { headers: hrAuthHeaders() });
      const data = await res.json();
      $('#statEmployees').textContent = data.filter(e => e.status === 'active').length;
      if (!data.length){
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No employees on file yet.</td></tr>';
        return;
      }
      tbody.innerHTML = data.map(e => `
        <tr>
          <td>${escapeHtml(e.full_name)}</td>
          <td>${escapeHtml(e.job_role)}</td>
          <td>${escapeHtml(e.hotel_name || '—')}</td>
          <td class="salary-figure">${e.current_salary != null ? Number(e.current_salary).toLocaleString() : '—'}</td>
          <td>${formatDate(e.hire_date)}</td>
          <td><span class="badge ${escapeHtml(e.status)}">${escapeHtml(e.status)}</span></td>
        </tr>`).join('');
    }catch(e){
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Could not reach the API.</td></tr>';
    }
  }

  async function loadPayrollStatus(){
    const tbody = $('#payrollTable tbody');
    try{
      const res = await fetch(base() + '/hr/payroll-status', { headers: hrAuthHeaders() });
      const data = await res.json();
      if (data.period_start){
        $('#payrollPeriodLabel').textContent =
          `Payroll status — ${formatDate(data.period_start)} to ${formatDate(data.period_end)}`;
      }
      const rows = data.employees || [];
      if (!rows.length){
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No active employees to show.</td></tr>';
        return;
      }
      const statusBadge = { paid: 'success', partial: 'pending', unpaid: 'error' };
      tbody.innerHTML = rows.map(r => `
        <tr>
          <td>${escapeHtml(r.full_name)}</td>
          <td>${escapeHtml(r.job_role)}</td>
          <td class="salary-figure">${Number(r.current_salary).toLocaleString()}</td>
          <td class="salary-figure">${Number(r.paid_amount).toLocaleString()}</td>
          <td class="salary-figure">${Number(r.remaining).toLocaleString()}</td>
          <td><span class="badge ${statusBadge[r.status] || ''}">${escapeHtml(r.status)}</span></td>
        </tr>`).join('');
    }catch(e){
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Could not reach the API.</td></tr>';
    }
  }

  async function loadSalesSummary(){
    const tbody = $('#salesTable tbody');
    try{
      const res = await fetch(base() + '/hr/sales-summary', { headers: hrAuthHeaders() });
      const data = await res.json();
      if (data.period_start){
        $('#salesPeriodLabel').textContent =
          `Sales — ${formatDate(data.period_start)} to ${formatDate(data.period_end)}`;
      }
      $('#statSalesTotal').textContent = '₹' + Number(data.total || 0).toLocaleString();
      $('#statSalesCount').textContent = data.entry_count || 0;

      const entries = data.entries || [];
      if (!entries.length){
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No sales logged for this period yet.</td></tr>';
        return;
      }
      tbody.innerHTML = entries.map(e => `
        <tr>
          <td>${formatDate(e.sale_date)}</td>
          <td>${escapeHtml(e.hotel_name)}</td>
          <td>${escapeHtml(e.category || '—')}</td>
          <td class="salary-figure">₹${Number(e.amount).toLocaleString()}</td>
          <td>${escapeHtml(e.entered_by || '—')}</td>
        </tr>`).join('');
    }catch(e){
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Could not reach the API.</td></tr>';
    }
  }

  function formatDateTime(iso){
    try{
      const d = new Date(iso);
      return d.toLocaleString();
    }catch(e){ return iso; }
  }

  async function loadAuditLog(){
    const tbody = $('#auditTable tbody');
    try{
      const res = await fetch(base() + '/hr/audit-log', { headers: hrAuthHeaders() });
      const data = await res.json();
      if (!Array.isArray(data) || !data.length){
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No actions logged yet.</td></tr>';
        return;
      }
      tbody.innerHTML = data.map(entry => {
        const statusClass = entry.status === 'success' ? 'confirmed' : 'cancelled';
        const detail = entry.status === 'success'
          ? (typeof entry.result === 'string' ? entry.result : JSON.stringify(entry.result))
          : (entry.error_message || '—');
        return `
          <tr>
            <td>${formatDateTime(entry.created_at)}</td>
            <td>${escapeHtml(entry.actor_key)}</td>
            <td>${escapeHtml(entry.action_type)}</td>
            <td><span class="badge ${statusClass}">${escapeHtml(entry.status)}</span></td>
            <td style="max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(detail)}">${escapeHtml(detail)}</td>
          </tr>`;
      }).join('');
    }catch(e){
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Could not reach the API.</td></tr>';
    }
  }

  $('#hrAskBtn').addEventListener('click', async () => {
    const q = $('#hrAskInput').value.trim();
    if (!q) return showToast('Type a question first.', true);
    const btn = $('#hrAskBtn');
    setLoading(btn, true);
    try{
      const res = await fetch(base() + '/hr/ask', {
        method:'POST',
        headers: hrAuthHeaders({'Content-Type':'application/json'}),
        body: JSON.stringify({ question: q })
      });
      const data = await res.json();
      $('#hrAskResult').classList.add('show');
      $('#hrAskSql').innerHTML = highlightSql(data.generated_sql || '(no query returned)');
      if (data.error){
        $('#hrAskResultWrap').innerHTML = `<div class="empty-state">${escapeHtml(data.error)}</div>`;
        return showToast(data.error, true);
      }
      renderHrResultTable(data.result || []);
    }catch(e){
      showToast('Request failed — check the API URL.', true);
    }finally{
      setLoading(btn, false);
    }
  });

  function renderHrResultTable(rows){
    const wrap = $('#hrAskResultWrap');
    if (!rows.length){
      wrap.innerHTML = '<div class="empty-state">Query ran successfully — no rows returned.</div>';
      return;
    }
    const cols = Object.keys(rows[0]);
    const thead = `<thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>`;
    const tbody = `<tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${escapeHtml(r[c])}</td>`).join('')}</tr>`).join('')}</tbody>`;
    wrap.innerHTML = `<table>${thead}${tbody}</table>`;
  }

  let currentHrActionId = null;

  // tab switching
  $$('#hrTabs .form-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      $$('#hrTabs .form-tab').forEach(t => t.classList.remove('active'));
      $$('#hrContent .action-form').forEach(f => f.classList.remove('active'));
      tab.classList.add('active');
      $('#hrform-' + tab.dataset.form).classList.add('active');
      $('#hrActionPreviewBox').classList.remove('show');
      $('#hrActionOutcomeBox').classList.remove('show');
    });
  });

  async function populateHrSelect(selectEl, url, valueFn, labelFn, placeholder, filterFn){
    try{
      const res = await fetch(base() + url, { headers: hrAuthHeaders() });
      let data = await res.json();
      if (Array.isArray(data) && filterFn) data = data.filter(filterFn);
      if (!Array.isArray(data) || !data.length){
        selectEl.innerHTML = `<option value="">No options available</option>`;
        return;
      }
      selectEl.innerHTML = `<option value="">${placeholder}</option>` +
        data.map(item => `<option value="${escapeHtml(valueFn(item))}">${escapeHtml(labelFn(item))}</option>`).join('');
    }catch(e){
      selectEl.innerHTML = `<option value="">Could not load options</option>`;
    }
  }

  function loadHrFormOptions(){
    populateHrSelect($('#hireHotel'), '/hotels', h => h.name, h => h.name, 'Select a hotel');
    const activeLabel = e => `${e.full_name} — ${e.job_role} (${e.hotel_name || 'no hotel'})`;
    const isActive = e => e.status === 'active';
    populateHrSelect($('#terminateEmployee'), '/hr/employees', e => e.id, activeLabel, 'Select an employee', isActive);
    populateHrSelect($('#salaryEmployee'), '/hr/employees', e => e.id, activeLabel, 'Select an employee', isActive);
    populateHrSelect($('#paymentEmployee'), '/hr/employees', e => e.id, activeLabel, 'Select an employee', isActive);
  }

  async function proposeHrAction(payload, endpoint){
    $('#hrActionOutcomeBox').classList.remove('show');
    try{
      const res = await fetch(base() + endpoint, {
        method:'POST',
        headers: hrAuthHeaders({'Content-Type':'application/json'}),
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.error){
        $('#hrActionPreviewBox').classList.remove('show');
        return showToast(data.error, true);
      }
      currentHrActionId = data.action_id;
      renderHrPreview(data.preview);
      $('#hrActionExpiry').textContent = data.message || '';
      $('#hrActionPreviewBox').classList.add('show');
    }catch(e){
      showToast('Request failed — check the API URL.', true);
    }
  }

  $('#hireBtn').addEventListener('click', async () => {
    const name = $('#hireName').value.trim(), role = $('#hireRole').value.trim();
    const hotel = $('#hireHotel').value, salary = $('#hireSalary').value;
    if (!name || !role || !hotel || !salary) return showToast('Fill in all fields first.', true);
    const btn = $('#hireBtn'); setLoading(btn, true);
    await proposeHrAction({ full_name: name, job_role: role, hotel_name: hotel, starting_salary: Number(salary) }, '/hr/action/hire');
    setLoading(btn, false);
  });

  $('#terminateBtn').addEventListener('click', async () => {
    const empId = $('#terminateEmployee').value;
    if (!empId) return showToast('Select an employee first.', true);
    const btn = $('#terminateBtn'); setLoading(btn, true);
    await proposeHrAction({ employee_id: Number(empId) }, '/hr/action/terminate');
    setLoading(btn, false);
  });

  $('#salaryBtn').addEventListener('click', async () => {
    const empId = $('#salaryEmployee').value, newSalary = $('#salaryNew').value;
    if (!empId || !newSalary) return showToast('Fill in all fields first.', true);
    const btn = $('#salaryBtn'); setLoading(btn, true);
    await proposeHrAction({ employee_id: Number(empId), new_salary: Number(newSalary) }, '/hr/action/salary');
    setLoading(btn, false);
  });

  $('#paymentBtn').addEventListener('click', async () => {
    const empId = $('#paymentEmployee').value, amount = $('#paymentAmount').value;
    const start = $('#paymentStart').value, end = $('#paymentEnd').value;
    if (!empId || !amount || !start || !end) return showToast('Fill in all fields first.', true);
    const btn = $('#paymentBtn'); setLoading(btn, true);
    await proposeHrAction({ employee_id: Number(empId), amount: Number(amount), period_start: start, period_end: end }, '/hr/action/payment');
    setLoading(btn, false);
  });

  function renderHrPreview(preview){
    const card = $('#hrActionPreviewCard');
    const rows = Object.entries(preview)
      .filter(([,v]) => v !== null && v !== undefined && v !== '')
      .map(([k,v]) => `<div class="preview-row"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(v)}</span></div>`)
      .join('');
    card.innerHTML = rows;
  }

  $('#hrConfirmBtn').addEventListener('click', async () => {
    if (!currentHrActionId) return;
    const btn = $('#hrConfirmBtn');
    setLoading(btn, true);
    try{
      const res = await fetch(base() + '/hr/action/confirm', {
        method:'POST',
        headers: hrAuthHeaders({'Content-Type':'application/json'}),
        body: JSON.stringify({ action_id: currentHrActionId })
      });
      const data = await res.json();
      $('#hrActionOutcomeBox').classList.add('show');
      const card = $('#hrActionOutcomeCard');
      if (data.error){
        card.innerHTML = `<span class="badge error">Error</span><p style="margin-top:10px;">${escapeHtml(data.error)}</p>`;
        showToast(data.error, true);
      }else{
        card.innerHTML = `<span class="badge success">Success</span><p style="margin-top:10px;">${escapeHtml(JSON.stringify(data))}</p>`;
        showToast('HR action completed.');
        $('#hrActionPreviewBox').classList.remove('show');
        currentHrActionId = null;
        loadEmployees();
        loadPayrollStatus();
        loadSalesSummary();
        loadAuditLog();
        loadHrFormOptions();
      }
    }catch(e){
      showToast('Request failed — check the API URL.', true);
    }finally{
      setLoading(btn, false);
    }
  });

  $('#hrDiscardBtn').addEventListener('click', () => {
    currentHrActionId = null;
    $('#hrActionPreviewBox').classList.remove('show');
  });

  $('#hrAskClear').addEventListener('click', () => {
    $('#hrAskInput').value = '';
    $('#hrAskResult').classList.remove('show');
  });

  // Auto-unlock HR if a manager key was saved this session
  if (savedManagerKey){
    $('#hrKeyInput').value = savedManagerKey;
    tryUnlockHr(savedManagerKey);
  }

  // ---------------- init ----------------
  checkConnection();
  loadHotels();
  loadBookings();
  loadActionFormOptions();
  setInterval(checkConnection, 15000);
})();

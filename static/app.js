'use strict';
const $ = id => document.getElementById(id);
let csrf = '', user = null, team = [], today = '', zone = 'Asia/Kolkata', currentView = '', openShift = null;
let stream = null, cameraMode = null, challenge = '', toastTimer, cameraRun = 0;
const escapeHTML = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(message, error = false) {
  $('notice').textContent = message; $('notice').classList.toggle('error', error); $('notice').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('notice').hidden = true, error ? 10000 : 5000);
}
async function api(path, method = 'GET', body) {
  const result = await fetch(path, {method, credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:body === undefined ? undefined : JSON.stringify(body)});
  const data = await result.json();
  if (!result.ok) {
    if (result.status === 401 && path !== '/api/login') await boot();
    throw new Error(data.error || 'Unable to complete the request.');
  }
  return data;
}
async function perform(fn) { try { await fn(); } catch (e) { notice(e.message, true); } }
const time = value => value ? new Intl.DateTimeFormat('en-IN', {hour:'2-digit',minute:'2-digit',timeZone:zone}).format(new Date(value)) : '—';
function personCell(name, code) {
  const initials = name.split(/\s+/).map(x => x[0]).slice(0,2).join('');
  return `<div class="person-cell"><span class="avatar">${escapeHTML(initials)}</span><div><strong>${escapeHTML(name)}</strong><small>${escapeHTML(code.toUpperCase())}</small></div></div>`;
}
function locationCell(loc) {
  if (!loc || !Number.isFinite(loc.lat) || !Number.isFinite(loc.lng)) return '—';
  const href = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(loc.lat + ',' + loc.lng)}`;
  return `<a class="location-link" href="${href}" target="_blank" rel="noopener noreferrer">View location ↗</a><small class="muted">Accuracy ±${Math.round(loc.accuracy)} m</small>`;
}
function attendanceTable(target, rows, month = false) {
  if (!rows.length) { $(target).innerHTML = '<div class="empty"><strong>No attendance recorded</strong>Records will appear here after a verified check-in.</div>'; return; }
  const adminActions=user?.admin?'<th>Admin</th>':'';
  $(target).innerHTML = `<div class="table-wrap"><table><thead><tr><th>Employee</th>${month ? '<th>Date</th>' : ''}<th>Check-in</th><th>Check-out</th><th>Hours</th><th>Status</th><th>Check-in location</th><th>Check-out location</th>${adminActions}</tr></thead><tbody>${rows.map(r => `<tr><td>${personCell(r.employee,r.code)}</td>${month ? `<td>${escapeHTML(r.date)}</td>` : ''}<td>${time(r.check_in)}</td><td>${time(r.check_out)}</td><td>${r.hours === null ? '—' : escapeHTML(r.hours.toFixed(2))}</td><td><span class="pill ${r.check_out ? 'neutral' : ''}">${r.check_out ? 'Completed' : 'At work'}</span></td><td>${locationCell(r.in_location)}</td><td>${locationCell(r.out_location)}</td>${user?.admin?`<td><div class="action-buttons"><button class="small-button" data-attedit="${r.id}">Edit</button><button class="small-button danger" data-attdelete="${r.id}">Delete</button></div></td>`:''}</tr>`).join('')}</tbody></table></div>`;
}

async function refreshOverview() {
  const [employees, dayRows, todayRows] = await Promise.all([api('/api/employees'), api('/api/attendance?date='+encodeURIComponent($('day-filter').value)), api('/api/attendance?date='+today)]);
  team = employees;
  const active = team.filter(e => e.active), codes = new Set(todayRows.map(r => r.code));
  $('stat-total').textContent = active.length; $('stat-in').textContent = todayRows.length;
  $('stat-working').textContent = todayRows.filter(r => !r.check_out).length;
  $('stat-away').textContent = active.filter(e => !codes.has(e.code)).length;
  attendanceTable('daily-table', dayRows);
}
async function refreshEmployees() {
  team = await api('/api/employees');
  if (!team.length) { $('employee-table').innerHTML = '<div class="empty"><strong>Build your Cosmos team</strong>Add your first employee, then register their face.</div>'; return; }
  $('employee-table').innerHTML = `<div class="table-wrap"><table><thead><tr><th>Employee</th><th>Department</th><th>Face</th><th>Biometric</th><th>Access</th><th>Actions</th></tr></thead><tbody>${team.map(e => `<tr><td>${personCell(e.name,e.code)}</td><td>${escapeHTML(e.department)}</td><td><span class="pill ${e.enrolled ? '' : 'warning'}">${e.enrolled ? 'Registered' : 'Not registered'}</span></td><td><span class="pill ${e.biometric_registered ? '' : 'warning'}">${e.biometric_registered ? 'Registered' : 'Not registered'}</span></td><td>${e.active ? 'Active' : 'Inactive'}</td><td><div class="action-buttons"><button class="small-button" data-edit="${e.id}">Edit</button>${e.active ? `<button class="small-button" data-enrol="${e.id}">${e.enrolled ? 'Re-register face' : 'Register face'}</button>` : ''}${e.enrolled ? `<button class="small-button" data-resetface="${e.id}">Remove face</button>` : ''}<button class="small-button" data-pin="${e.id}">Reset PIN</button>${e.biometric_registered ? `<button class="small-button" data-resetbio="${e.id}">Reset biometric</button>` : ''}<button class="small-button" data-toggle="${e.id}">${e.active ? 'Deactivate' : 'Activate'}</button><button class="small-button danger" data-delete="${e.id}">Remove</button></div></td></tr>`).join('')}</tbody></table></div>`;
}
async function refreshMine() {
  const identity = await api('/api/session');
  if (!identity.user) throw new Error('Please sign in again.');
  user = identity.user; today = identity.today;
  const [rows, status] = await Promise.all([api('/api/attendance?date='+today),api('/api/my-status')]);
  openShift = status.open_shift;
  $('greeting').textContent = 'Hello, ' + user.name.split(' ')[0] + '.';
  const finished = rows.some(r => r.check_out);
  $('employee-status').textContent = !user.enrolled ? 'Your administrator needs to register your face first.' : openShift ? 'Checked in at ' + time(openShift.check_in) + ' · ' + openShift.date : finished ? 'Your attendance is complete for today.' : 'Ready for a new working day.';
  $('start-attendance').textContent = openShift ? 'Check out with face verification' : 'Check in with face verification';
  $('start-attendance').disabled = !user.enrolled || (!openShift && finished);
  attendanceTable('my-table', rows);
}
const views = {overview:['Attendance overview',"A clear view of your team's working day.",'▦'],employees:['Employees','The people behind every working day.','⊞'],reports:['Monthly reports','Attendance records, ready for your monthly review.','▤'],checkin:['My attendance','Check in, get to work, and make today count.','◎']};
async function navigate(view) {
  if (!views[view] || (user.admin ? view === 'checkin' : view !== 'checkin')) throw new Error('This page is not available.');
  currentView = view;
  document.querySelectorAll('.panel-view').forEach(el => el.hidden = el.id !== view+'-panel');
  document.querySelectorAll('.nav-button').forEach(el => el.classList.toggle('active',el.dataset.view===view));
  $('page-title').textContent=views[view][0]; $('page-subtitle').textContent=views[view][1]; $('breadcrumb').textContent=views[view][0];
  if(view === 'overview') await refreshOverview();
  if(view === 'employees') await refreshEmployees();
  if(view === 'reports') attendanceTable('monthly-table',await api('/api/attendance?month='+$('month-filter').value),true);
  if(view === 'checkin') await refreshMine();
}
async function showApp() {
  $('login-view').hidden = true; $('app-view').hidden = false;
  $('account-name').textContent=user.name; $('timezone-label').textContent=zone;
  $('today-label').textContent=new Intl.DateTimeFormat('en-IN',{day:'numeric',month:'short',year:'numeric',timeZone:zone}).format(new Date());
  $('day-filter').value=today; $('month-filter').value=today.slice(0,7);
  const names = user.admin ? ['overview','employees','reports'] : ['checkin'];
  $('navigation').innerHTML = names.map(view=>`<button class="nav-button" data-view="${view}"><span class="nav-icon" aria-hidden="true">${views[view][2]}</span>${view==='overview'?'Overview':views[view][0]}</button>`).join('');
  await navigate(names[0]);
}
async function boot() {
  const info = await api('/api/session'); csrf=info.csrf; user=info.user; today=info.today; zone=info.timezone;
  if(user) await showApp(); else {$('app-view').hidden=true; $('login-view').hidden=false;}
}
function b64urlToBytes(value){const pad='='.repeat((4-value.length%4)%4),b64=(value+pad).replace(/-/g,'+').replace(/_/g,'/'),raw=atob(b64);return Uint8Array.from(raw,c=>c.charCodeAt(0));}
function bytesToB64url(value){const bytes=new Uint8Array(value);let raw='';bytes.forEach(b=>raw+=String.fromCharCode(b));return btoa(raw).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
function decodeCreationOptions(o){o.challenge=b64urlToBytes(o.challenge);o.user.id=b64urlToBytes(o.user.id);(o.excludeCredentials||[]).forEach(c=>c.id=b64urlToBytes(c.id));return o;}
function decodeRequestOptions(o){o.challenge=b64urlToBytes(o.challenge);(o.allowCredentials||[]).forEach(c=>c.id=b64urlToBytes(c.id));return o;}
function credentialJSON(c){return {id:c.id,rawId:bytesToB64url(c.rawId),type:c.type,authenticatorAttachment:c.authenticatorAttachment||undefined,clientExtensionResults:c.getClientExtensionResults(),response:{clientDataJSON:bytesToB64url(c.response.clientDataJSON),authenticatorData:c.response.authenticatorData?bytesToB64url(c.response.authenticatorData):undefined,signature:c.response.signature?bytesToB64url(c.response.signature):undefined,userHandle:c.response.userHandle?bytesToB64url(c.response.userHandle):null,attestationObject:c.response.attestationObject?bytesToB64url(c.response.attestationObject):undefined,transports:c.response.getTransports?c.response.getTransports():undefined}};}
async function registerBiometric(){if(!window.PublicKeyCredential)throw new Error('Biometric/passkey login is not supported by this browser.');const options=decodeCreationOptions(await api('/api/biometric/register/options','POST',{}));const credential=await navigator.credentials.create({publicKey:options});if(!credential)throw new Error('Biometric registration was cancelled.');await api('/api/biometric/register/verify','POST',credentialJSON(credential));notice('Biometric login registered on this device.');}
async function loginBiometric(){const code=$('login-code').value.trim();if(!code)throw new Error('Enter your Employee ID first.');if(!window.PublicKeyCredential)throw new Error('Biometric/passkey login is not supported by this browser.');const options=decodeRequestOptions(await api('/api/biometric/login/options','POST',{code}));const credential=await navigator.credentials.get({publicKey:options});if(!credential)throw new Error('Biometric login was cancelled.');const data=await api('/api/biometric/login/verify','POST',credentialJSON(credential));csrf=data.csrf;user=data.user;await showApp();}
$('biometric-login').addEventListener('click',()=>perform(loginBiometric));
$('register-biometric').addEventListener('click',()=>perform(registerBiometric));
$('login-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{
  const button=e.currentTarget.querySelector('button');button.disabled=true;
  try {const data=await api('/api/login','POST',Object.fromEntries(new FormData($('login-form'))));csrf=data.csrf;user=data.user;$('login-form').reset();await showApp();}finally{button.disabled=false;}
});});
$('logout').addEventListener('click',()=>perform(async()=>{await api('/api/logout','POST',{});stopCamera();await boot();}));
$('navigation').addEventListener('click',e=>{const button=e.target.closest('[data-view]');if(button)perform(()=>navigate(button.dataset.view));});
$('day-filter').addEventListener('change',()=>perform(refreshOverview));
$('month-filter').addEventListener('change',()=>perform(()=>navigate('reports')));
$('export').addEventListener('click',()=>perform(async()=>{
  const month=$('month-filter').value;if(!month)throw new Error('Choose a month first.');
  const response=await fetch('/api/export?month='+encodeURIComponent(month));
  if(!response.ok){const error=await response.json();throw new Error(error.error);}
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='cosmos-attendance-'+month+'.csv';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}));
$('add-employee').addEventListener('click',()=>{const f=$('employee-form');f.reset();$('employee-id').value='';$('employee-dialog-title').textContent='Add employee';$('employee-dialog-note').textContent='Create an employee with a private 4-digit PIN.';$('pin-label').hidden=false;$('pin-help').hidden=false;$('employee-save').textContent='Create employee';f.elements.pin.required=true;$('employee-dialog').showModal();});
$('employee-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{
  const button=e.currentTarget.querySelector('button[type=submit]');button.disabled=true;
  try{const data=Object.fromEntries(new FormData($('employee-form'))),id=data.employee_id;delete data.employee_id;if(id){delete data.pin;await api('/api/employees/'+id,'PATCH',data);notice('Employee details updated.');}else{await api('/api/employees','POST',data);notice('Employee created. Register their face next.');}$('employee-dialog').close();await refreshEmployees();}finally{button.disabled=false;}
});});
$('employee-table').addEventListener('click',e=>perform(async()=>{
  const button=e.target.closest('button');if(!button)return;const id=Number(button.dataset.enrol||button.dataset.toggle||button.dataset.edit||button.dataset.pin||button.dataset.resetbio||button.dataset.resetface||button.dataset.delete),employee=team.find(p=>p.id===id);if(!employee)return;
  if(button.dataset.enrol){await startCamera({employee});return;}
  if(button.dataset.edit){const f=$('employee-form');f.reset();$('employee-id').value=employee.id;f.elements.name.value=employee.name;f.elements.code.value=employee.code.toUpperCase();f.elements.department.value=employee.department;$('employee-dialog-title').textContent='Edit employee';$('employee-dialog-note').textContent='Change employee identity or department.';$('pin-label').hidden=true;$('pin-help').hidden=true;f.elements.pin.required=false;$('employee-save').textContent='Save changes';$('employee-dialog').showModal();return;}
  if(button.dataset.pin){const pin=prompt(`Enter a new 4-digit PIN for ${employee.name}:`);if(pin===null)return;if(!/^\d{4}$/.test(pin))throw new Error('PIN must be exactly 4 digits.');await api('/api/employees/'+employee.id+'/reset-pin','POST',{pin});notice('Employee PIN reset.');return;}
  if(button.dataset.resetface){if(!confirm(`Remove the registered attendance face for ${employee.name}?`))return;await api('/api/employees/'+employee.id+'/reset-face','POST',{});await refreshEmployees();notice('Attendance face removed.');return;}
  if(button.dataset.resetbio){if(!confirm(`Remove all biometric/passkey logins for ${employee.name}? They can register again after signing in with their PIN.`))return;await api('/api/employees/'+employee.id+'/reset-biometric','POST',{});await refreshEmployees();notice('Biometric login reset.');return;}
  if(button.dataset.toggle){if(!confirm(`${employee.active?'Deactivate':'Activate'} ${employee.name}'s account?`))return;await api('/api/employees/'+employee.id+'/active','POST',{active:!employee.active});await refreshEmployees();notice('Employee access updated.');return;}
  if(button.dataset.delete){if(!confirm(`Permanently remove ${employee.name}, including their attendance history and saved biometric credentials?`))return;await api('/api/employees/'+employee.id,'DELETE',{});await refreshEmployees();notice('Employee removed.');}
}));
document.querySelectorAll('.close-dialog').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
function stopCamera(){cameraRun++;if(stream)stream.getTracks().forEach(track=>track.stop());stream=null;$('video').srcObject=null;}
$('camera-dialog').addEventListener('close',stopCamera);
window.addEventListener('pagehide',stopCamera);
async function startCamera(mode){
  stopCamera();const run=cameraRun;cameraMode=mode;challenge='';$('capture-button').disabled=true;$('consent').checked=false;
  $('consent-label').hidden=!mode.employee;$('camera-title').textContent=mode.employee?'Register '+mode.employee.name:(mode.action==='out'?'Verify check-out':'Verify check-in');
  $('camera-description').textContent=mode.employee?'Administrator: confirm the employee’s identity before enrolment.':'Face the camera. Your location will be captured when you submit.';
  $('camera-status').textContent='Starting camera…';$('camera-dialog').showModal();
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('Camera access requires HTTPS and a supported browser.');
    const nextStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:{ideal:640},height:{ideal:480}},audio:false});
    if(run!==cameraRun){nextStream.getTracks().forEach(t=>t.stop());return;}
    stream=nextStream;$('video').srcObject=stream;await $('video').play();
    if(!mode.employee)challenge=(await api('/api/capture','POST',{})).challenge;
    if(run!==cameraRun)return;
    $('camera-status').textContent='Camera ready. Keep your face inside the guide.';$('capture-button').textContent=mode.employee?'Capture and register':'Capture and verify';$('capture-button').disabled=false;
  }catch(e){$('camera-status').textContent=e.name==='NotAllowedError'?'Camera permission denied. Allow camera access in your browser settings.':e.message;stopCamera();}
}
$('start-attendance').addEventListener('click',()=>perform(async()=>{await refreshMine();if(!$('start-attendance').disabled)await startCamera({action:openShift?'out':'in'});}));
function getLocation(){return new Promise((resolve,reject)=>{
  if(!navigator.geolocation)return reject(new Error('Location is not supported by this browser.'));
  navigator.geolocation.getCurrentPosition(p=>resolve({lat:p.coords.latitude,lng:p.coords.longitude,accuracy:p.coords.accuracy,timestamp:p.timestamp}),()=>reject(new Error('Unable to get location. Allow location access, enable GPS, and try again.')),{enableHighAccuracy:true,timeout:20000,maximumAge:0});
});}
$('capture-button').addEventListener('click',()=>perform(async()=>{
  const mode=cameraMode,run=cameraRun,button=$('capture-button');
  if(mode.employee&&!$('consent').checked)throw new Error('Confirm employee consent before registering their face.');
  if(!$('video').videoWidth)throw new Error('Camera is not ready. Try opening it again.');
  button.disabled=true;
  try{
    let location;
    if(!mode.employee){$('camera-status').textContent='Getting your current location…';location=await getLocation();if(run!==cameraRun)return;challenge=(await api('/api/capture','POST',{})).challenge;}
    if(run!==cameraRun)return;
    const canvas=document.createElement('canvas'),video=$('video'),scale=Math.min(1,800/video.videoWidth,800/video.videoHeight);
    canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
    const photo=canvas.toDataURL('image/jpeg',.85);$('camera-status').textContent='Verifying and saving…';
    if(mode.employee){await api('/api/employees/'+mode.employee.id+'/enrol','POST',{photo,consent:true});$('camera-dialog').close();await refreshEmployees();notice('Face registered successfully.');}
    else{await api('/api/attendance','POST',{photo,location,challenge,action:mode.action});$('camera-dialog').close();await refreshMine();notice(mode.action==='in'?'Checked in successfully. Have a good day.':'Checked out successfully.');}
  }catch(e){$('camera-status').textContent=e.message;throw e;}finally{button.disabled=false;}
}));
async function attendanceAdminAction(e){
  const edit=e.target.closest('[data-attedit]'),del=e.target.closest('[data-attdelete]');if(!edit&&!del)return;
  const id=Number((edit||del).dataset.attedit||(edit||del).dataset.attdelete);
  if(del){if(!confirm('Delete this attendance record permanently?'))return;await api('/api/attendance/'+id,'DELETE',{});currentView==='reports'?await navigate('reports'):await refreshOverview();notice('Attendance record deleted.');return;}
  const source=await api('/api/attendance?'+(currentView==='reports'?'month='+$('month-filter').value:'date='+$('day-filter').value));const r=source.find(x=>x.id===id);if(!r)throw new Error('Attendance record not found.');
  const cin=prompt('Check-in time (ISO/date-time). Example: 2026-09-25T09:00',r.check_in.slice(0,16));if(cin===null)return;const cout=prompt('Check-out time. Leave blank for open shift.',r.check_out?r.check_out.slice(0,16):'');if(cout===null)return;
  await api('/api/attendance/'+id,'PATCH',{check_in:cin,check_out:cout});currentView==='reports'?await navigate('reports'):await refreshOverview();notice('Attendance corrected.');
}
$('daily-table').addEventListener('click',e=>perform(()=>attendanceAdminAction(e)));
$('monthly-table').addEventListener('click',e=>perform(()=>attendanceAdminAction(e)));
setInterval(()=>{if(user){$('clock').textContent=new Intl.DateTimeFormat('en-IN',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:zone}).format(new Date());}},1000);
// Read-only tools expose only what the signed-in user can already access.
if(document.modelContext?.registerTool){
  const lifecycle=new AbortController();
  Promise.resolve(document.modelContext.registerTool({name:'read_visible_attendance',title:'Read attendance',description:'Read attendance records for the currently selected date or month. Requires sign-in and preserves the same employee/admin access rules.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute:async input=>{
    if(!input||Object.keys(input).length)throw new Error('This tool takes no arguments.');
    if(!user)throw new Error('Sign in first.');
    if(currentView==='employees')throw new Error('Open Overview, My attendance or Monthly reports first.');
    const query=currentView==='reports'?'month='+$('month-filter').value:'date='+(currentView==='overview'?$('day-filter').value:today);
    return {records:await api('/api/attendance?'+query)};
  }},{signal:lifecycle.signal})).catch(()=>{});
  window.addEventListener('pagehide',()=>lifecycle.abort());
}
perform(boot);

const $=id=>document.getElementById(id);
const HISTORY_KEY="agn_assistant_history_v1";
let busy=false,lastQuestion="";
function csrf(){const match=document.cookie.match(/(?:^|; )agn_csrf=([^;]*)/);return match?decodeURIComponent(match[1]):""}
function el(tag,className,text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node}
function history(){try{const value=JSON.parse(localStorage.getItem(HISTORY_KEY)||"[]");return Array.isArray(value)?value.slice(-20):[]}catch{return []}}
function saveHistory(value){localStorage.setItem(HISTORY_KEY,JSON.stringify(value.slice(-20)))}
function referenceUrl(ref){return ref.type==="note"?"/#note-"+encodeURIComponent(ref.id):ref.type==="ai_daily"?"/ai-daily#item-"+encodeURIComponent(ref.id):"/ai-daily"}
function renderTurn(turn){
  $("emptyState")?.remove();
  const user=el("article","message user");user.append(el("div","message-label","あなた"));user.append(el("div","answer",turn.question));$("conversation").append(user);
  const assistant=el("article","message assistant");assistant.append(el("div","message-label","AI GROWTH ASSISTANT"));
  assistant.append(el("div","answer",turn.answer));
  if(turn.references?.length){const refs=el("div","references");refs.append(el("h3","", "参照した記録"));turn.references.forEach(ref=>{const link=el("a","reference");link.href=referenceUrl(ref);const time=el("time","",String(ref.date||"").slice(0,10));link.append(time,el("strong","",ref.title||"学習記録"),el("p","",ref.preview||""));refs.append(link)});assistant.append(refs)}
  const notice=el("div","notice",turn.provider==="gemini"?"回答は表示された参照記録を根拠に生成されました。":"検索結果のみを表示しています。");assistant.append(notice);
  if(turn.failed){const retry=el("button","retry","もう一度試す");retry.type="button";retry.onclick=()=>ask(turn.question);assistant.append(retry)}
  $("conversation").append(assistant)
}
async function ask(question){
  question=(question||"").trim();if(!question||busy)return;busy=true;lastQuestion=question;$("sendButton").disabled=true;$("question").disabled=true;$("formStatus").textContent="学習記録を検索しています…";
  $("emptyState")?.remove();const user=el("article","message user");user.append(el("div","message-label","あなた"),el("div","answer",question));$("conversation").append(user);
  const pending=el("article","message assistant");pending.append(el("div","message-label","AI GROWTH ASSISTANT"),el("div","answer loading","NotesとAI Dailyから関連する記録を探しています…"));$("conversation").append(pending);pending.scrollIntoView({behavior:"smooth",block:"end"});
  try{const response=await fetch("/api/assistant/ask",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({question,sources:["notes","ai_daily","reports"]})});if(response.status===401){location.assign("/login?next=/assistant");return}const data=await response.json();if(!response.ok)throw new Error(data.detail?.[0]?.msg||data.detail||"通信に失敗しました");pending.remove();user.remove();const turn={question,answer:data.answer,references:data.references||[],provider:data.provider};renderTurn(turn);const items=history();items.push(turn);saveHistory(items);$("question").value=""}
  catch(error){pending.remove();user.remove();renderTurn({question,answer:"回答を取得できませんでした。通信状態を確認して再試行してください。",references:[],provider:"error",failed:true});$("formStatus").textContent=String(error.message||error)}
  finally{busy=false;$("sendButton").disabled=false;$("question").disabled=false;if($("formStatus").textContent.includes("検索"))$("formStatus").textContent="Enterで送信・Shift+Enterで改行";$("question").focus();window.scrollTo({top:document.body.scrollHeight,behavior:"smooth"})}
}
async function loadSuggestions(){try{const response=await fetch("/api/assistant/suggestions");const data=await response.json();$("suggestionList").replaceChildren(...data.suggestions.map(value=>{const button=el("button","chip",value);button.type="button";button.onclick=()=>ask(value);return button}))}catch{$("suggestionList").textContent="質問候補を読み込めませんでした。"}}
$("askForm").addEventListener("submit",event=>{event.preventDefault();ask($("question").value)});
$("question").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();ask(event.currentTarget.value)}});
$("clearHistory").onclick=()=>{localStorage.removeItem(HISTORY_KEY);$("conversation").replaceChildren();const empty=el("div","empty");empty.id="emptyState";empty.append(el("span","","✦"),el("h2","","履歴をクリアしました"),el("p","","新しい質問から始められます。"));$("conversation").append(empty)};
history().forEach(renderTurn);loadSuggestions();

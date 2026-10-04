// static/app.js
const $ = (selector) => document.querySelector(selector);
function esc(str){if(str===null||str===undefined)return "";return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\"/g,"&quot;").replace(/'/g,"&#039;");}
function money(num){return Number(num||0).toLocaleString("th-TH",{minimumFractionDigits:2,maximumFractionDigits:2});}
function fmtDate(isoStr){if(!isoStr)return "-";try{const p=isoStr.split("T")[0].split("-");return p.length===3?`${p[2]}/${p[1]}/${p[0]}`:isoStr;}catch(e){return isoStr;}}
function statusOf(record){if(record.return_date)return{cls:"returned",label:"คืนแล้ว"};if(record.is_overdue||Number(record.fine_amount)>0)return{cls:"overdue",label:"เลยกำหนด"};return{cls:"borrowing",label:"กำลังยืม"};}
function showMessage(type,text,opts={}){const area=$("#flash-area");if(!area)return;if(opts.clear)area.innerHTML="";const box=document.createElement("div");box.className=`flash ${type}`;box.textContent=text;area.appendChild(box);}
async function api(path,options={}){const baseUrl=typeof API_BASE_URL!=="undefined"?API_BASE_URL:"";const url=path.startsWith("http")?path:`${baseUrl}${path}`;try{const res=await fetch(url,options);const ct=res.headers.get("content-type");const data=ct&&ct.includes("application/json")?await res.json():{message:await res.text()};return{ok:res.ok,status:res.status,data};}catch(err){return{ok:false,status:0,data:{message:"ไม่สามารถเชื่อมต่อ Backend ได้: "+err.message}};}}

// Compatibility layer for the booking page's inline submit handler.
(() => {
  const nativeFetch=window.fetch.bind(window);
  window.fetch=async(input,init={})=>{
    const url=typeof input==="string"?input:(input&&input.url)||"";
    if(url.endsWith("/api/book")&&init&&init.body){
      try{
        const payload=JSON.parse(init.body);
        const purpose=document.querySelector("#purpose");
        const pin=document.querySelector("#booking_pin");
        if(purpose)payload.purpose=purpose.value.trim();
        if(pin)payload.booking_pin=pin.value.trim();
        init={...init,body:JSON.stringify(payload)};
      }catch(_){}
    }
    const res=await nativeFetch(input,init);
    if(url.endsWith("/api/book")&&res.ok){
      try{
        const data=await res.clone().json();
        if(data.line_link_code){
          const code=String(data.line_link_code);
          setTimeout(()=>{const area=document.querySelector("#flash-area");if(!area)return;const box=document.createElement("div");box.className="flash success";box.innerHTML=`<strong>ขั้นตอนต่อไป: ผูก LINE</strong><br>เปิด LINE OA แล้วส่งข้อความ <strong>ผูก ${esc(code)}</strong><br><small>รหัสนี้ใช้ได้ครั้งเดียวและมีอายุ 15 นาที</small>`;area.appendChild(box);window.scrollTo({top:0,behavior:"smooth"});},0);
        }
      }catch(_){}
    }
    return res;
  };
})();
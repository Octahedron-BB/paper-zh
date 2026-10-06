/**
 * 机构反代文献抓取与书签小工具 (Bookmarklet)
 */

export function buildBookmarkletCode(appUrl = window.location.origin): string {
  // 书签小工具：用户在 nature.publinks.top 页面点击书签，直接将当前页面的完整 HTML 传递给伴读应用
  const code = `
javascript:(function(){
  try {
    const html = document.documentElement.outerHTML;
    const url = window.location.href;
    const m = url.match(/(s[0-9]{5}-[0-9]{3}-[0-9]{5}-[0-9a-z])/i);
    const docId = m ? m[1] : ('doc_' + Date.now());
    sessionStorage.setItem('paper_transfer_' + docId, html);
    const target = '${appUrl}/?import_doc=' + encodeURIComponent(docId);
    window.open(target, '_blank');
  } catch(e) {
    alert('传送失败: ' + e.message);
  }
})();
  `.trim().replace(/\s+/g, ' ')

  return code
}

export async function fetchFromInstitutionalProxy(
  docId: string,
  proxyUrl: string,
  cookie?: string
): Promise<string> {
  const cleanId = docId.split('/').pop()?.replace('.html', '').replace('.pdf', '') || docId

  // 拼接目标地址，例如 https://nature.publinks.top/articles/s41572-026-00741-7
  let targetUrl = ''
  if (proxyUrl.includes('{doc_id}')) {
    targetUrl = proxyUrl.replace('{doc_id}', cleanId)
  } else if (proxyUrl.includes('nature.publinks.top')) {
    const base = proxyUrl.replace(/\/+$/, '')
    targetUrl = `${base}/articles/${cleanId}`
  } else {
    // 假设是通用 CORS 代理服务
    targetUrl = `${proxyUrl}?url=${encodeURIComponent(`https://nature.publinks.top/articles/${cleanId}`)}`
    if (cookie) {
      targetUrl += `&cookie=${encodeURIComponent(cookie)}`
    }
  }

  const res = await fetch(targetUrl, {
    headers: cookie ? { 'x-proxy-cookie': cookie } : {},
  })

  if (!res.ok) {
    throw new Error(`反代请求失败 (${res.status}): ${res.statusText}`)
  }

  return await res.text()
}

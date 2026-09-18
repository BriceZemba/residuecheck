import { useEffect } from 'react'

/** Fades `.reveal` elements in as they scroll into view (CSS does the motion; reduced motion shows them at once). */
export function useReveal() {
  useEffect(() => {
    const seen = new WeakSet<Element>()
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add('in')
            io.unobserve(e.target)
          }
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 },
    )
    const scan = () =>
      document.querySelectorAll('.reveal').forEach((el) => {
        if (!seen.has(el)) {
          seen.add(el)
          io.observe(el)
        }
      })
    scan()
    const mo = new MutationObserver(scan)
    mo.observe(document.body, { childList: true, subtree: true })
    return () => {
      io.disconnect()
      mo.disconnect()
    }
  }, [])
}

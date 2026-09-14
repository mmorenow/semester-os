import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

/** Agent output renderer. Raw HTML stays disabled so agent output can't inject markup. */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn('text-[13px] leading-relaxed text-foreground/90', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children: c }) => <h3 className="mt-4 mb-2 text-sm font-semibold text-foreground first:mt-0">{c}</h3>,
          h2: ({ children: c }) => <h4 className="mt-4 mb-2 text-sm font-semibold text-foreground first:mt-0">{c}</h4>,
          h3: ({ children: c }) => (
            <h5 className="mt-3 mb-1.5 text-xs font-semibold text-muted-foreground first:mt-0">{c}</h5>
          ),
          p: ({ children: c }) => <p className="mb-3 last:mb-0">{c}</p>,
          ul: ({ children: c }) => <ul className="mb-3 space-y-1 pl-4 last:mb-0">{c}</ul>,
          ol: ({ children: c }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{c}</ol>,
          li: ({ children: c }) => (
            <li className="relative pl-3 before:absolute before:left-0 before:text-muted-foreground before:content-['-'] [ol_&]:pl-0 [ol_&]:before:content-none">
              {c}
            </li>
          ),
          strong: ({ children: c }) => <strong className="font-semibold text-foreground">{c}</strong>,
          em: ({ children: c }) => <em className="italic">{c}</em>,
          a: ({ children: c, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              className="text-primary underline underline-offset-2 hover:no-underline"
            >
              {c}
            </a>
          ),
          code: ({ children: c }) => (
            <code className="rounded-sm bg-muted px-1 py-0.5 font-mono text-[12px] text-foreground">{c}</code>
          ),
          pre: ({ children: c }) => (
            <pre className="mb-3 overflow-x-auto rounded-md border border-border bg-muted/50 p-3 font-mono text-[12px] last:mb-0">
              {c}
            </pre>
          ),
          blockquote: ({ children: c }) => (
            <blockquote className="mb-3 border-l-2 border-border pl-3 text-muted-foreground last:mb-0">{c}</blockquote>
          ),
          hr: () => <hr className="my-4 border-border" />,
          table: ({ children: c }) => (
            <div className="mb-3 overflow-x-auto last:mb-0">
              <table className="w-full text-left text-[12px]">{c}</table>
            </div>
          ),
          th: ({ children: c }) => (
            <th className="border-b border-border py-1.5 pr-3 font-medium text-muted-foreground">{c}</th>
          ),
          td: ({ children: c }) => <td className="border-b border-border/60 py-1.5 pr-3 align-top">{c}</td>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

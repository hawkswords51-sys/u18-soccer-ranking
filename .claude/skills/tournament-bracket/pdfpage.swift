import PDFKit
import AppKit
let a = CommandLine.arguments
let doc = PDFDocument(url: URL(fileURLWithPath: a[1]))!
let page = doc.page(at: Int(a[2])! - 1)!
let r = page.bounds(for: .mediaBox)
let scale: CGFloat = CGFloat(Double(a[4])!) / max(r.width, r.height)
let img = page.thumbnail(of: NSSize(width: r.width*scale, height: r.height*scale), for: .mediaBox)
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: a[3]))
